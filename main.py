import base64
import io
import os
import tempfile

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageDraw, ImageFont
from starlette.requests import Request

load_dotenv()

ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY", "GLtJ5r9nHHA0DozQo21D")
WORKSPACE_NAME = "charbels-workspace-dyeep"
WORKFLOW_ID = "general-segmentation-api"

app = FastAPI()
templates = Jinja2Templates(directory="templates")


def get_client():
    from inference_sdk import InferenceHTTPClient

    return InferenceHTTPClient(
        api_url="https://serverless.roboflow.com",
        api_key=ROBOFLOW_API_KEY,
    )


def draw_boxes(image: Image.Image, predictions: list) -> Image.Image:
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=16)
    except Exception:
        font = ImageFont.load_default()

    for pred in predictions:
        x = pred.get("x", 0)
        y = pred.get("y", 0)
        w = pred.get("width", 0)
        h = pred.get("height", 0)
        label = pred.get("class", "pill")
        confidence = pred.get("confidence", 0)

        x0 = x - w / 2
        y0 = y - h / 2
        x1 = x + w / 2
        y1 = y + h / 2

        draw.rectangle([x0, y0, x1, y1], outline="#00FF00", width=3)
        text = f"{label} {confidence:.0%}"
        draw.rectangle([x0, y0 - 22, x0 + len(text) * 9, y0], fill="#00FF00")
        draw.text((x0 + 2, y0 - 20), text, fill="#000000", font=font)

    return image


def extract_predictions(result) -> list:
    """
    run_workflow returns a list with one element (per image).
    Each element is a dict of named outputs from the workflow.
    We search all output values for a list that looks like predictions.
    """
    if not result:
        return []

    item = result[0] if isinstance(result, list) else result
    print("Workflow raw output:", item)  # logged server-side for debugging

    # Common output key names Roboflow workflows use
    for key in ("predictions", "output", "detections", "results"):
        val = item.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict) and "predictions" in val:
            return val["predictions"]

    # Fallback: return first list value found
    for val in item.values():
        if isinstance(val, list):
            return val

    return []


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    contents = await file.read()

    try:
        image = Image.open(io.BytesIO(contents)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")

    suffix = os.path.splitext(file.filename or "image.jpg")[1] or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        client = get_client()
        result = client.run_workflow(
            workspace_name=WORKSPACE_NAME,
            workflow_id=WORKFLOW_ID,
            images={"image": tmp_path},
            parameters={"classes": ["pill"]},
            use_cache=True,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Workflow error: {e}")
    finally:
        os.unlink(tmp_path)

    predictions = extract_predictions(result)
    count = len(predictions)

    annotated = draw_boxes(image.copy(), predictions)
    buf = io.BytesIO()
    annotated.save(buf, format="JPEG", quality=90)
    annotated_b64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "count": count,
        "annotated_image": f"data:image/jpeg;base64,{annotated_b64}",
        "predictions": predictions,
    }

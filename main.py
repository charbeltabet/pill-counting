import base64
import io
import os
import tempfile

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageDraw, ImageFont, ImageOps
from starlette.requests import Request

load_dotenv()

ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY", "GLtJ5r9nHHA0DozQo21D")
WORKSPACE_NAME = "charbels-workspace-dyeep"
WORKFLOW_ID = "detect-count-and-visualize"

DEMO_DIR = os.path.join(os.path.dirname(__file__), "public", "demo_images")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

app = FastAPI()
app.mount("/public", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "public")), name="public")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def draw_boxes(image: Image.Image, predictions: list) -> Image.Image:
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=16)
    except Exception:
        font = ImageFont.load_default()

    for i, pred in enumerate(predictions, start=1):
        x = pred.get("x", 0)
        y = pred.get("y", 0)
        w = pred.get("width", 0)
        h = pred.get("height", 0)
        confidence = pred.get("confidence", 0)
        label = pred.get("class", "pill")

        x0, y0 = x - w / 2, y - h / 2
        x1, y1 = x + w / 2, y + h / 2

        draw.rectangle([x0, y0, x1, y1], outline="#00FF00", width=3)

        # Label above: "#1: 94%"
        top_text = f"#{i}: {confidence:.0%}"
        tw = len(top_text) * 9
        draw.rectangle([x0, y0 - 22, x0 + tw, y0], fill="#00FF00")
        draw.text((x0 + 2, y0 - 20), top_text, fill="#000000", font=font)

        # Label below: class name
        bw = len(label) * 9
        draw.rectangle([x0, y1, x0 + bw, y1 + 20], fill="#00FF00")
        draw.text((x0 + 2, y1 + 2), label, fill="#000000", font=font)

    return image


def get_client():
    from inference_sdk import InferenceHTTPClient

    return InferenceHTTPClient(
        api_url="https://serverless.roboflow.com",
        api_key=ROBOFLOW_API_KEY,
    )



@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/demo-images")
async def demo_images():
    if not os.path.isdir(DEMO_DIR):
        return {"images": []}
    files = sorted(
        f for f in os.listdir(DEMO_DIR)
        if os.path.splitext(f)[1].lower() in ALLOWED_EXTENSIONS
    )
    return {"images": [f"/public/demo_images/{f}" for f in files]}


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    contents = await file.read()

    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(contents))).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        image.save(tmp, format="JPEG", quality=95)
        tmp_path = tmp.name

    try:
        client = get_client()
        result = client.run_workflow(
            workspace_name=WORKSPACE_NAME,
            workflow_id=WORKFLOW_ID,
            images={"image": tmp_path},
            use_cache=True,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Workflow error: {e}")
    finally:
        os.unlink(tmp_path)

    item = result[0] if isinstance(result, list) else result
    count = item.get("count_objects", 0)

    # predictions is {"image": {...}, "predictions": [...]}
    raw_preds = item.get("predictions", {})
    predictions = raw_preds.get("predictions", []) if isinstance(raw_preds, dict) else []

    annotated = draw_boxes(image.copy(), predictions)
    buf = io.BytesIO()
    annotated.save(buf, format="JPEG", quality=90)
    annotated_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    return {
        "count": count,
        "annotated_image": annotated_b64,
        "predictions": predictions,
    }

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        port=8000,
        reload=True,
    )

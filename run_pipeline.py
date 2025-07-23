# run_pipeline.py
import os
from PIL import Image
from ultralytics import YOLO
from surya.layout import LayoutPredictor
from surya.recognition import RecognitionPredictor
from surya.detection import DetectionPredictor

import fitz
import re

# import `ollama`
import json
import subprocess

PDF_FOLDER = "testpdf"
IMAGE_FOLDER = "extracted_images"
DB_PATH = "questions.db"
MODEL_PATH = "best.pt"
INPUT_IMAGE = "extracted_images/algone-12025-exam_page5.png"
KEY_PDF_PATH = "algone-12025-sk.pdf"
OUTPUT_DIR = "output_questions"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def classify_topic(text):
    prompt = f"""Classify the following Algebra I question into only one of the following topics: The Real Number System, Quantities, Seeing Structure in Expressions, Arithmetic with Polynomials and Rational
Expressions, Creating Equations, Reasoning with Equations and Inequalities, Interpreting Functions, Building Functions, 'Linear, Quadratic, and Exponential Models', Interpreting categorical and quantitative data.

{text}

Respond with only the topic."""
    
    try:
        result = subprocess.run(
            ["ollama", "run", "llama3"],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=15
        )
        return result.stdout.strip().split('\n')[0]
    except Exception as e:
        print(f"Ollama classification failed: {e}")
        return "unknown"

def grabKeyAnswers(PDF_PATH):
    scoringKeyDict = {}
    doc = fitz.open(PDF_PATH)
    full_text = ""
    for page in doc:
        full_text += page.get_text()
        entries = full_text.splitlines()
        current = 9
        while (entries[current + 4] == "MC"):
            scoringKeyDict[entries[current + 2]] = entries[current + 3]
            current += 6
    print(scoringKeyDict)
    return scoringKeyDict

def extract_question_text(ocr_results) -> str:
    all_lines = []
    for ocr in ocr_results:
        for line in ocr.text_lines:
            if line.text:
                all_lines.append(line.text.strip())
    return "\n".join(all_lines).strip()

def run_pipeline():
    model = YOLO(MODEL_PATH)
    results = model.predict(source=INPUT_IMAGE, conf=0.85, save=False)
    full_image = Image.open(INPUT_IMAGE)
    # predictor = TexifyPredictor()

    question_data = []
    key = grabKeyAnswers(KEY_PDF_PATH)
    for i, r in enumerate(results):
        boxes = r.boxes.xyxy.cpu().numpy()  # x1, y1, x2, y2
        class_ids = r.boxes.cls.cpu().numpy().astype(int)
        class_names = r.names
        for j, (box, class_id) in enumerate(zip(boxes, class_ids)):
            x1, y1, x2, y2 = map(int, box)
            cropped = full_image.crop((x1, y1, x2, y2))
            label = class_names[class_id]
            LABEL_DIR = os.path.join(OUTPUT_DIR, label)
            os.makedirs(LABEL_DIR, exist_ok=True)
            # Save each cropped question image
            cropped_path = os.path.join(LABEL_DIR, f"question_{i}_{j}.png")
            cropped.save(cropped_path)

            # === STEP 3: Run Surya OCR on each cropped image ===
            recognition_predictor = RecognitionPredictor()
            detection_predictor = DetectionPredictor()
            try:
                predictions = recognition_predictor([cropped], det_predictor=detection_predictor)
            except:
                cropped.save(os.path.join(LABEL_DIR, f"untranslatedq_{i}_{j}.png"))
            # tex_result = predictor([cropped])
            print(predictions)
            question_text = extract_question_text(predictions)
            print(question_text)
            topic = classify_topic(question_text)
            if len(question_text) == 0 or not question_text.split(' ')[0].isdigit():
                continue
            question_data.append({
                "image": cropped_path,
                "text": question_text,
                "type": label[:3],
                "topic": topic,
                "answer": key[question_text.split(' ')[0]]
            })
    

    print(question_data)


if __name__ == "__main__":
    run_pipeline()

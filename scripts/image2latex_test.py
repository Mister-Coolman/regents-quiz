from surya.recognition import RecognitionPredictor
from surya.detection import DetectionPredictor
from PIL import Image
import os
from bs4 import BeautifulSoup

def extract_question_text(ocr_results) -> str:
    all_lines = []
    for ocr in ocr_results:
        for line in ocr.text_lines:
            if line.text:
                all_lines.append(line.text.strip())
    return "\n".join(all_lines).strip()

predictor = RecognitionPredictor()
detector = DetectionPredictor()

def strip_html_tags(text):
    soup = BeautifulSoup(text, "html.parser")
    for sup in soup.find_all("sup"):
        sup.replace_with("^" + sup.get_text())
    return soup.get_text()

cropped = Image.open('output_questions/mcqQuestionBlock/question_2_2_a46ced39.png')  # Assuming INPUT_IMAGE is defined

ocr_results = predictor([cropped], det_predictor=detector)
question_text = extract_question_text(ocr_results)

print(strip_html_tags(question_text))
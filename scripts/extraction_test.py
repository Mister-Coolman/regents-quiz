import fitz  # PyMuPDF
import re

def grabKeyAnswers(PDF_PATH):
    scoringKeyDict = {}
    doc = fitz.open(PDF_PATH)
    full_text = ""
    for page in doc:
        full_text += page.get_text()
    entries = full_text.splitlines()
    if "examination" in entries[0].lower():
        current = 1
        while (current < len(entries)):
            if (entries[current] == "MC"):
                scoringKeyDict[entries[current - 2]] = entries[current - 1]
            current += 1
        print(scoringKeyDict)
        return scoringKeyDict
    elif "FOR TEACHERS ONLY" in entries[0].upper():
        pattern = r"\((\d{1,2})\)\s+(?:\.\s+){5}([1-4])"
        matches = re.findall(pattern, full_text)
        answer_key = {}
        for num, ans in matches:
            answer_key[num] = ans
        return answer_key


# Example usage
pdf_path = "pdfs/keys/algone12020-sk.pdf"
answers = grabKeyAnswers(pdf_path)
print(answers)

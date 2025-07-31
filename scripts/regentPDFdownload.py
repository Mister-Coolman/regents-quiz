import os
import requests

BASE_URL = "https://www.nysedregents.org/algebraone"
EXAM_DIR = os.path.join("pdfs", "exams")
KEY_DIR = os.path.join("pdfs", "keys")

os.makedirs(EXAM_DIR, exist_ok=True)
os.makedirs(KEY_DIR, exist_ok=True)

years = range(2015, 2026)
months = {1,6,8}

for year in years:
    for mm in months:
        yy = str(year)[2:]  # last 2 digits of year
        for filetype, folder in [("exam", EXAM_DIR), ("sk", KEY_DIR)]:
            filename = f"algtwo{mm}{year}-{filetype}.pdf"
            url = f"{BASE_URL}/{mm}{yy}/{filename}"
            output_path = os.path.join(folder, filename)
            if os.path.exists(output_path):
                continue
            try:
                r = requests.get(url)
                if r.status_code == 200:
                    with open(output_path, "wb") as f:
                        f.write(r.content)
                    print(f"✅ Downloaded: {url}")
                elif year <= 2019 and filetype == "sk":
                    filename = f"algone{mm}{year}-rg.pdf"
                    url = f"{BASE_URL}/{mm}{yy}/{filename}"

                    r = requests.get(url)
                    if r.status_code == 200:
                        with open(output_path, "wb") as f:
                            f.write(r.content)
                        print(f"✅ Downloaded: {url}")
                    else:
                        print(f"❌ Not found ({r.status_code}): {url}")
                else:
                    print(f"❌ Not found ({r.status_code}): {url}")
            except Exception as e:
                print(f"⚠️ Error downloading {filename}: {e}")

import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# --- CONFIG ---
website_url = "https://www.nysedregents.org/algebraone/"   # Change this to the target website
output_folder = "algebraonepdfs"     # Folder to save PDFs

# --- SETUP ---
os.makedirs(output_folder, exist_ok=True)
response = requests.get(website_url)
soup = BeautifulSoup(response.text, "html.parser")

# --- FIND & DOWNLOAD PDF LINKS ---
pdf_links = set()
for link in soup.find_all("a", href=True):
    href = link["href"]
    if href.lower().endswith(".pdf"):
        full_url = urljoin(website_url, href)
        pdf_links.add(full_url)

print(f"Found {len(pdf_links)} PDFs.")

for url in pdf_links:
    filename = os.path.join(output_folder, url.split("/")[-1])
    try:
        print(f"Downloading: {url}")
        r = requests.get(url)
        with open(filename, "wb") as f:
            f.write(r.content)
    except Exception as e:
        print(f"Failed to download {url}: {e}")
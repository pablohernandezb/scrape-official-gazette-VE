import argparse
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

def download_gaceta_smart(name, start, end):
    print(f"--- Processing {name} Gazettes ---")
    folder = f"Gacetas_2026_{name}"
    if not os.path.exists(folder):
        os.makedirs(folder)

    for num in range(start, end + 1):
        page_url = f"http://www.gacetaoficial.gob.ve/gacetas/{num}"
        
        try:
            # 1. Load the wrapper page
            response = requests.get(page_url, timeout=15)
            if response.status_code != 200:
                print(f"Skipping {num}: Page not found.")
                continue

            # 2. Parse the HTML to find the actual PDF link
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # We look for <a> tags, <embed> tags, or <iframe> tags that mention ".pdf"
            # Based on the site structure, it's often in an <embed> or an <a> link
            pdf_link = None
            
            # Strategy A: Look for an explicit download link
            link_tag = soup.find('a', href=lambda x: x and '.pdf' in x.lower())
            if link_tag:
                pdf_link = link_tag['href']
            
            # Strategy B: Look for the embedded viewer source
            if not pdf_link:
                embed_tag = soup.find(['embed', 'iframe'], src=lambda x: x and '.pdf' in x.lower())
                if embed_tag:
                    pdf_link = embed_tag['src']

            if pdf_link:
                # Convert relative links (like "/files/abc.pdf") to absolute URLs
                final_pdf_url = urljoin(page_url, pdf_link)
                file_path = os.path.join(folder, f"Gaceta_{num}.pdf")

                # 3. Download the actual PDF file
                print(f"Found PDF for {num}. Downloading...")
                pdf_data = requests.get(final_pdf_url, stream=True)
                
                with open(file_path, 'wb') as f:
                    for chunk in pdf_data.iter_content(chunk_size=1024):
                        f.write(chunk)
            else:
                print(f"Could not find a PDF link on page {num}.")

        except Exception as e:
            print(f"Error on Gazette {num}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download Venezuelan Official Gazette PDFs.")
    parser.add_argument("--ord-start",  type=int, default=43287, help="Ordinaria start number (default: 43287)")
    parser.add_argument("--ord-end",    type=int, default=43325, help="Ordinaria end number (default: 43325)")
    parser.add_argument("--ext-start",  type=int, default=6954,  help="Extraordinaria start number (default: 6954)")
    parser.add_argument("--ext-end",    type=int, default=6990,  help="Extraordinaria end number (default: 6990)")
    args = parser.parse_args()

    download_gaceta_smart("Ordinaria",      args.ord_start, args.ord_end)
    download_gaceta_smart("Extraordinaria", args.ext_start, args.ext_end)
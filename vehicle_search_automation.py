import requests
from bs4 import BeautifulSoup
import time

def parse_cargurus_listings(html_content):
    """
    Parses CarGurus search result HTML and returns a list of dictionaries.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Target all listing tiles using the reliable data-testid
    listings = soup.select('[data-testid="srp-listing-tile"]')
    results = []

    for item in listings:
        try:
            # 2. Extract Link
            link_tag = item.select_one('[data-testid="car-blade-link"]')
            link = link_tag.get('href') if link_tag else None
            full_link = f"https://www.cargurus.com{link}" if link and link.startswith('/') else link

            # 3. Extract Title
            title_tag = item.select_one('[data-testid="srp-tile-listing-title"] h4')
            title = title_tag.get('title') if title_tag and title_tag.has_attr('title') else "N/A"

            # 4. Extract Image
            img_tag = item.select_one('[data-testid="srp-tile-media"] img')
            img_url = img_tag.get('src') if img_tag else None

            # 5. Extract Sponsored Status
            # We look in the parent container (tileSlot) to find the sibling sponsored-text element
            parent_container = item.find_parent()
            sponsored_tag = parent_container.select_one('[data-testid="sponsored-text"]')
            is_sponsored = True if sponsored_tag else False

            results.append({
                "title": title,
                "link": full_link,
                "image_url": img_url,
                "is_sponsored": is_sponsored
            })

        except Exception as e:
            print(f"Error parsing an item: {e}")
            continue
            
    return results

# --- Main Execution Block ---
if __name__ == "__main__":
    # Example: If you have your HTML saved in a file
    # with open("cargurus_page.html", "r", encoding="utf-8") as f:
    #     html_content = f.read()
    
    # Example: If using requests (Note: CarGurus often requires headers to avoid bot detection)
    url = "YOUR_CARGURUS_SEARCH_URL_HERE"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = parse_cargurus_listings(response.text)
            
            # Print findings
            for entry in data:
                print("-" * 30)
                print(f"Title: {entry['title']}")
                print(f"Sponsored: {entry['is_sponsored']}")
                print(f"Link: {entry['link']}")
        else:
            print(f"Failed to retrieve page: {response.status_code}")
            
    except Exception as e:
        print(f"Automation Error: {e}")

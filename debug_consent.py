"""Debug script to find consent/accept buttons on Forebet"""
import undetected_chromedriver as uc
import time

options = uc.ChromeOptions()
options.add_argument('--disable-gpu')
options.add_argument('--no-sandbox')
driver = uc.Chrome(options=options)

try:
    driver.get('https://www.forebet.com/en/football-tips-and-predictions-for-today')
    time.sleep(8)
    
    # Zapisz HTML
    with open('forebet_consent_debug.html', 'w', encoding='utf-8') as f:
        f.write(driver.page_source)
    print(f"HTML saved: {len(driver.page_source)} chars")
    
    # Znajdź wszystkie przyciski
    buttons = driver.find_elements('tag name', 'button')
    print(f'\nBUTTONS ({len(buttons)}):')
    for b in buttons[:20]:
        txt = b.text[:50] if b.text else "(no text)"
        cls = b.get_attribute("class")[:50] if b.get_attribute("class") else ""
        print(f'  - "{txt}" | class="{cls}"')
    
    # Szukaj consent/accept/agree w tekście
    all_elements = driver.find_elements('xpath', '//*[contains(text(),"Accept") or contains(text(),"ACCEPT") or contains(text(),"Agree") or contains(text(),"AGREE") or contains(text(),"Consent") or contains(text(),"consent") or contains(text(),"OK") or contains(text(),"Continue")]')
    print(f'\nELEMENTS with Accept/Agree/Consent ({len(all_elements)}):')
    for el in all_elements[:15]:
        tag = el.tag_name
        txt = el.text[:60] if el.text else ""
        print(f'  - <{tag}> "{txt}"')
    
    # Szukaj iframe z consent
    iframes = driver.find_elements('tag name', 'iframe')
    print(f'\nIFRAMES ({len(iframes)}):')
    for i in iframes[:10]:
        id_attr = i.get_attribute("id") or ""
        src = i.get_attribute("src") or ""
        print(f'  - id="{id_attr}" src="{src[:80]}"')
    
    # Sprawdź CMP (Consent Management Platform)
    cmp_elements = driver.find_elements('xpath', '//*[contains(@class,"cmp") or contains(@class,"consent") or contains(@class,"gdpr") or contains(@class,"cookie") or contains(@id,"cmp") or contains(@id,"consent")]')
    print(f'\nCMP/CONSENT elements ({len(cmp_elements)}):')
    for el in cmp_elements[:10]:
        tag = el.tag_name
        id_attr = el.get_attribute("id") or ""
        cls = el.get_attribute("class") or ""
        print(f'  - <{tag}> id="{id_attr}" class="{cls[:60]}"')

finally:
    driver.quit()
    print('\nDone!')

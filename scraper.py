"""
scraper.py — Scraping Vinted avec extraction correcte du titre via attribut title du lien
"""
import logging
import os
from playwright.async_api import async_playwright

log = logging.getLogger(__name__)

async def fetch_vinted_items(search_url: str) -> list[dict]:
    try:
        return await _fetch_via_playwright(search_url)
    except Exception as e:
        log.error(f"Erreur scraper Vinted: {e}")
        return []


async def _fetch_via_playwright(search_url: str) -> list[dict]:
    session = os.getenv("VINTED_SESSION", "")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="fr-FR",
            viewport={"width": 1280, "height": 720},
            extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9"}
        )

        if session:
            await context.add_cookies([{
                "name": "_vinted_fr_session",
                "value": session,
                "domain": ".vinted.fr",
                "path": "/",
                "secure": True,
            }])

        page = await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        # Interception des réponses API Vinted (méthode la plus fiable)
        api_items = []

        async def handle_response(response):
            if "/api/v2/catalog/items" in response.url and response.status == 200:
                try:
                    data = await response.json()
                    for item in data.get("items", []):
                        photo = item.get("photo") or {}
                        api_items.append({
                            "url": f"https://www.vinted.fr/items/{item['id']}",
                            "title": item.get("title", "Sans titre"),
                            "price": f"{item.get('price', '?')} €",
                            "size": item.get("size_title") or "N/A",
                            "image": photo.get("url", ""),
                            "brand": item.get("brand_title", ""),
                        })
                except Exception as e:
                    log.warning(f"Erreur parsing JSON API: {e}")

        page.on("response", handle_response)

        try:
            log.info(f"Chargement de {search_url}")
            await page.goto(search_url, timeout=60000, wait_until="networkidle")
            await page.wait_for_timeout(3000)

            # Méthode 1 : API interceptée (données complètes et fiables)
            if api_items:
                log.info(f"✅ {len(api_items)} articles via API interceptée")
                return api_items[:10]

            # Méthode 2 : Extraction depuis les liens (l'attribut title contient le vrai nom)
            log.warning("API non interceptée, extraction via attributs title des liens...")

            results = await page.evaluate("""
                () => {
                    const results = [];
                    const seen = new Set();
                    const links = document.querySelectorAll('a[href*="/items/"][title]');

                    links.forEach(link => {
                        const url = link.href;
                        if (seen.has(url) || !url.includes('/items/')) return;
                        seen.add(url);

                        // Le titre est dans l'attribut title du lien (ex: "Nike Air Max 90 - Taille 42 - 45,00 €")
                        const fullTitle = link.getAttribute('title') || '';

                        // Extraire le titre (avant le premier tiret ou toute la chaine)
                        let title = fullTitle.split(' · ')[0].trim() || fullTitle.split(' - ')[0].trim() || fullTitle || 'Article Vinted';

                        // Extraire le prix depuis le title (contient souvent "45,00 €")
                        let price = 'Voir sur Vinted';
                        const priceMatch = fullTitle.match(/(\d+[\.,]\d+)\s*€/);
                        if (priceMatch) price = priceMatch[0];

                        // Extraire la taille depuis le title
                        let size = 'N/A';
                        const sizeMatch = fullTitle.match(/\b(XS|S|M|L|XL|XXL|XXXL|\d{2,3})\b/);
                        if (sizeMatch) size = sizeMatch[0];

                        // Image dans le parent de la carte
                        let image = '';
                        const card = link.closest('div') || link.parentElement;
                        if (card) {
                            const img = card.querySelector('img');
                            if (img) image = img.src || img.dataset.src || '';
                        }

                        if (title.length > 2) {
                            results.push({ url, title, price, size, image });
                        }
                    });

                    return results;
                }
            """)

            if results and len(results) > 0:
                log.info(f"✅ {len(results)} articles via attributs title")
                return results[:10]

            # Méthode 3 : dernier recours
            log.warning("Fallback final sur les liens /items/")
            links = await page.query_selector_all("a[href*='/items/']")
            final_results = []
            seen = set()
            for link in links[:15]:
                href = await link.get_attribute("href")
                if not href or href in seen:
                    continue
                seen.add(href)
                full_url = "https://www.vinted.fr" + href if href.startswith("/") else href
                title = await link.get_attribute("title") or "Article Vinted"
                final_results.append({
                    "url": full_url,
                    "title": title[:60] if title else "Article Vinted",
                    "price": "Voir sur Vinted",
                    "size": "N/A",
                    "image": "",
                })

            log.info(f"✅ {len(final_results)} articles via liens")
            return final_results[:10]

        finally:
            await browser.close()

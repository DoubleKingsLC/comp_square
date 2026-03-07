import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page()
        await pg.goto('https://www.overleaf.com/legal')
        await pg.wait_for_load_state('domcontentloaded')
        html = await pg.evaluate("""() => {
            const e = document.getElementById('Cookies');
            if(!e) return 'NOT_FOUND';
            
            return {
                tag: e.tagName,
                className: e.className,
                textContentLen: e.textContent.length,
                parentTag: e.parentElement ? e.parentElement.tagName : null,
                nextSibling: e.nextElementSibling ? e.nextElementSibling.tagName : null,
                innerHTMLLen: e.innerHTML.length
            };
        }""")
        print('Cookies Element Details:', html)
        
        # Test the extraction logic verbatim
        extracted = await pg.evaluate("""() => {
            const target = document.getElementById('Cookies') || document.querySelector('[name="Cookies"]');
            if (!target) return 'No target';
            
            const tagPattern = /^H[1-6]$/i;
            const startLevel = tagPattern.test(target.tagName) ? parseInt(target.tagName[1]) : 6;
            
            const wrapper = document.createElement('div');
            wrapper.appendChild(target.cloneNode(true));
            
            let current = target.nextElementSibling;
            let siblings_grabbed = 0;
            while (current) {
                if (tagPattern.test(current.tagName)) {
                    const lvl = parseInt(current.tagName[1]);
                    if (lvl <= startLevel) break;
                }
                wrapper.appendChild(current.cloneNode(true));
                siblings_grabbed++;
                current = current.nextElementSibling;
            }
            
            return {
                startLevel: startLevel,
                siblingsGrabbed: siblings_grabbed,
                extractedLen: wrapper.innerText.length
            };
        }""")
        print('Extraction test:', extracted)
        
        await b.close()
asyncio.run(main())

import re, html, sys
def extract(path):
    h = open(path, encoding='utf-8', errors='ignore').read()
    h = re.sub(r'<script.*?</script>', '', h, flags=re.S)
    h = re.sub(r'<style.*?</style>', '', h, flags=re.S)
    # drop hidden anti-scrape spans
    h = re.sub(r'<span[^>]*display\s*:\s*none[^>]*>.*?</span>', '', h, flags=re.S|re.I)
    h = re.sub(r'<br\s*/?>', '\n', h)
    h = re.sub(r'</p>', '\n', h)
    t = re.sub(r'<[^>]+>', '', h)
    t = html.unescape(t)
    lines = [x.strip() for x in t.splitlines() if x.strip()]
    return lines
def is_en(s):
    if re.search(r'[一-鿿]', s): return False
    letters = len(re.findall(r'[A-Za-z]', s))
    return letters >= 4 and letters/len(s) > 0.5
if __name__ == '__main__':
    lines = extract(sys.argv[1])
    out = [s for s in lines if is_en(s)]
    print('\n'.join(out))

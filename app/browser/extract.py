"""页面价格启发式抽取：美团/抖音/淘宝/京东浏览器取数共用的 DOM 解析。

不依赖特定平台的 class 名（改版易失效），而是找「短文本块里的 ¥ 价格 +
一行像标题的文字」。同一卡片出现多个价格时：第一个视为现价，最大值视为
划线原价（用于折扣计算）。宁可少抓不错抓。
"""

EXTRACT_JS = """() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('div,li,a').forEach(el => {
    if (el.children.length > 6) return;
    const text = (el.innerText || '').trim();
    if (!text || text.length > 400) return;
    const ms = [...text.matchAll(/[¥￥]\\s*(\\d+(?:\\.\\d{1,2})?)/g)];
    if (!ms.length) return;
    const prices = ms.map(m => parseFloat(m[1])).filter(p => p > 0);
    if (!prices.length) return;
    const price = prices[0];
    const original = prices.length > 1 ? Math.max(...prices) : null;
    const lines = text.split('\\n').map(s => s.trim()).filter(Boolean);
    const title = lines.find(l => l.length > 4 && !/[¥￥]/.test(l) && !/^\\d+(\\.\\d+)?$/.test(l));
    if (!title) return;
    const key = title + price;
    if (seen.has(key)) return;
    seen.add(key);
    out.push({title: title.slice(0, 60), price, original: original && original > price ? original : null});
  });
  return out.slice(0, 30);
}"""

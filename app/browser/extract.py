"""页面价格启发式抽取：美团/抖音等浏览器取数共用的 DOM 解析。

不依赖特定平台的 class 名（改版易失效），而是找「短文本块里的 ¥ 价格 +
一行像标题的文字」。宁可少抓不错抓。
"""

EXTRACT_JS = """() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('div,li,a').forEach(el => {
    if (el.children.length > 6) return;
    const text = (el.innerText || '').trim();
    if (!text || text.length > 400) return;
    const m = text.match(/[¥￥]\\s*(\\d+(?:\\.\\d{1,2})?)/);
    if (!m) return;
    const lines = text.split('\\n').map(s => s.trim()).filter(Boolean);
    const title = lines.find(l => l.length > 4 && !/[¥￥]/.test(l) && !/^\\d+(\\.\\d+)?$/.test(l));
    if (!title) return;
    const key = title + m[1];
    if (seen.has(key)) return;
    seen.add(key);
    out.push({title: title.slice(0, 60), price: parseFloat(m[1]), extra: lines.slice(0, 4)});
  });
  return out.slice(0, 30);
}"""

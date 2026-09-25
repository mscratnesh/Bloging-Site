// Builds book/Momentum_Investing_Book.docx from momentum_study.json, book/book_extra.json and book/charts/*.png.
// Run: py book/make_charts.py && node book/build_book.js
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell, WidthType,
  BorderStyle, ShadingType, ImageRun, PageBreak, TableOfContents, Header, Footer, PageNumber, LevelFormat,
  TabStopType, TabStopPosition,
} = require("docx");

const ROOT = path.resolve(__dirname, "..");
const S = JSON.parse(fs.readFileSync(path.join(ROOT, "momentum_study.json"), "utf8"));
const X = JSON.parse(fs.readFileSync(path.join(__dirname, "book_extra.json"), "utf8"));
const E = JSON.parse(fs.readFileSync(path.join(ROOT, "etf_study.json"), "utf8"));

// ------------------------------------------------------------------ formatting helpers
const pct = (v, dp = 1, sign = false) => (v == null ? "–" : (sign && v > 0 ? "+" : "") + (v * 100).toFixed(dp) + "%");
const pts = v => (v > 0 ? "+" : "") + (v * 100).toFixed(1) + " pts";
const num = (v, dp = 2) => (v == null ? "–" : Number(v).toFixed(dp));
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fdate = s => (s ? `${+s.slice(8, 10)} ${MON[+s.slice(5, 7) - 1]} ${s.slice(0, 4)}` : "–");
const fmonth = s => (s ? `${MON[+s.slice(5, 7) - 1]} ${s.slice(0, 4)}` : "–");
const lakh = v => "₹" + v.toFixed(2) + " lakh";

const B = S.baseCase, N = S.benchmarks[0];
const SV = S.survivorship, L = S.luck, R = S.risk, T = R.trades, M = S.marketMa, G = S.goldCash, SL = S.stopLoss;
const sens = name => S.sensitivity.find(g => g.group.startsWith(name)).rows;
const row = (name, label) => sens(name).find(r => r.label.startsWith(label));
const ma = n => M.rows.find(r => r.ma === n);
const years = Object.keys(M.yearly["200"]);
const yr = y => M.yearly["200"][y], yrN = y => M.yearly.nifty500[y];
const monthly = row("Market filter", "200-DMA, checked at month-end");
const pitGrid = S.grid;
const cell = (g, n, k) => g.find(x => x.topN === n && x.exitRank === k);
const bestYear = years.reduce((a, y) => (yr(y) > yr(a) ? y : a));
const worstYear = years.reduce((a, y) => (yr(y) < yr(a) ? y : a));
const pitStop = SL.grid.find(g => g.universe.includes("point-in-time"));
const pitGold = G.grid.find(g => g.universe.includes("point-in-time"));
const mf = SL.marketFilter.find(m => m.universe.includes("point-in-time"));
const cap = c => S.capacity.find(x => x.capital === c);

// ------------------------------------------------------------------ document building blocks
const FONT = "Calibri", SERIF = "Georgia";
const INK = "17201B", ACCENT = "A8492F", MUTED = "667069", SOFT = "F3EFE8", LINE = "D9DDD5";
const PAGE_W = 11906, MARGIN = 1247, CONTENT_W = PAGE_W - 2 * MARGIN; // A4, ~2.2 cm margins

// Inline markup: **bold**, _italic_
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|_[^_]+_)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), bold: true, ...base }));
    else out.push(new TextRun({ text: t.slice(1, -1), italics: true, ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}

const body = [];
const P = (text, opts = {}) => body.push(new Paragraph({ children: runs(text), spacing: { after: 140, line: 300 }, ...opts }));
const H1 = text => body.push(new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun(text)] }));
const H2 = text => body.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(text)] }));
const H3 = text => body.push(new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(text)] }));
const bullets = items => items.forEach(t => body.push(new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: runs(t), spacing: { after: 80, line: 290 } })));
let listNo = 0;
const steps = items => {
  listNo += 1;
  items.forEach(t => body.push(new Paragraph({ numbering: { reference: "steps", level: 0, instance: listNo }, children: runs(t), spacing: { after: 80, line: 290 } })));
};
const callout = (title, text) => body.push(new Paragraph({
  children: [new TextRun({ text: title + " ", bold: true, color: ACCENT }), ...runs(text)],
  shading: { type: ShadingType.CLEAR, fill: SOFT, color: "auto" },
  border: { left: { style: BorderStyle.SINGLE, size: 18, color: ACCENT, space: 8 } },
  spacing: { before: 120, after: 200, line: 290 }, indent: { left: 180, right: 180 },
}));
const quote = (text, who) => {
  body.push(new Paragraph({ children: [new TextRun({ text: "“" + text + "”", italics: true, size: 24, font: SERIF, color: INK })], indent: { left: 567, right: 567 }, spacing: { before: 160, after: 40 } }));
  body.push(new Paragraph({ children: [new TextRun({ text: "— " + who, color: MUTED, size: 20 })], indent: { left: 567 }, spacing: { after: 220 } }));
};
const pageBreak = () => body.push(new Paragraph({ children: [new PageBreak()] }));

function pngSize(file) {
  const b = fs.readFileSync(file);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
}
let figNo = 0;
function figure(file, caption) {
  const f = path.join(__dirname, "charts", file);
  const { w, h } = pngSize(f);
  const width = 600, height = Math.round((width * h) / w);
  figNo += 1;
  body.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 }, keepNext: true,
    children: [new ImageRun({ type: "png", data: fs.readFileSync(f), transformation: { width, height }, altText: { title: caption, description: caption, name: file } })] }));
  body.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 },
    children: [new TextRun({ text: `Figure ${figNo}. `, bold: true, size: 18, color: MUTED }), new TextRun({ text: caption, size: 18, color: MUTED })] }));
}

let tableNo = 0;
function table(head, rows, opts = {}) {
  const n = head.length;
  const widths = opts.widths
    ? opts.widths.map(w => Math.round((w / opts.widths.reduce((a, b) => a + b, 0)) * CONTENT_W))
    : Array(n).fill(Math.floor(CONTENT_W / n));
  widths[widths.length - 1] += CONTENT_W - widths.reduce((a, b) => a + b, 0);
  const border = { style: BorderStyle.SINGLE, size: 4, color: LINE };
  const borders = { top: border, bottom: border, left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" }, right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" } };
  const mk = (text, i, header, hl) => new TableCell({
    width: { size: widths[i], type: WidthType.DXA }, borders,
    shading: header ? { type: ShadingType.CLEAR, fill: "EDEFE9", color: "auto" } : hl ? { type: ShadingType.CLEAR, fill: "F6EDE6", color: "auto" } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ alignment: i === 0 || opts.leftCols?.includes(i) ? AlignmentType.LEFT : AlignmentType.RIGHT,
      children: runs(String(text), { size: header ? 17 : 19, bold: header || hl ? true : undefined, color: header ? MUTED : INK }) })],
  });
  tableNo += 1;
  if (opts.title) body.push(new Paragraph({ keepNext: true, spacing: { before: 160, after: 80 },
    children: [new TextRun({ text: `Table ${tableNo}. `, bold: true, size: 18, color: MUTED }), new TextRun({ text: opts.title, size: 18, color: MUTED })] }));
  body.push(new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: widths,
    rows: [new TableRow({ tableHeader: true, children: head.map((h, i) => mk(h, i, true)) }),
      ...rows.map(r => new TableRow({ cantSplit: true, children: r.cells.map((c, i) => mk(c, i, false, r.hl)) }))],
  }));
  body.push(new Paragraph({ spacing: { after: 120 }, children: [] }));
}
const r_ = (cells, hl = false) => ({ cells, hl });

// ------------------------------------------------------------------ title pages
const titlePage = [
  new Paragraph({ spacing: { before: 2600 }, children: [new TextRun({ text: "LET MONEY EARN  ·  RESEARCH", color: ACCENT, bold: true, size: 20, characterSpacing: 40 })] }),
  new Paragraph({ spacing: { before: 300, after: 200 }, children: [new TextRun({ text: "Riding the Winners", font: SERIF, size: 76, bold: true, color: INK })] }),
  new Paragraph({ spacing: { after: 600 }, children: [new TextRun({ text: "A plain-English guide to momentum investing in India, with a six-year honest backtest", font: SERIF, size: 32, color: MUTED })] }),
  new Paragraph({ border: { top: { style: BorderStyle.SINGLE, size: 8, color: ACCENT, space: 12 } }, spacing: { after: 120 },
    children: [new TextRun({ text: `What it is · where it came from · why it works · how to run it · ${pct(B.cagr, 1)} a year on the Nifty 500, tested the honest way`, size: 22, color: INK })] }),
  new Paragraph({ spacing: { before: 2400 }, children: [new TextRun({ text: `Data to ${fdate(S.asOf)}`, size: 20, color: MUTED })] }),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ spacing: { before: 400, after: 160 }, children: [new TextRun({ text: "Before you read", bold: true, size: 26, font: SERIF })] }),
  new Paragraph({ spacing: { after: 140, line: 290 }, children: runs("This book is for information and education only. It is **not investment advice** and not a recommendation to buy or sell any security. Everything in it is based on a **backtest**: rules applied to past prices to see what would have happened. Backtests are hypothetical. Real trading has costs, delays and emotions that a backtest can't fully capture, and past results do not guarantee future returns. Stock names appear only because the rules picked them in the past; they are not suggestions. Please do your own research, and speak to a SEBI-registered adviser before investing.") }),
  new Paragraph({ spacing: { after: 140, line: 290 }, children: runs(`Price data: Yahoo Finance. Index lists: NSE Indices (current and archived copies via the Wayback Machine). Study period: ${fdate(B.from)} to ${fdate(B.to)}.`) }),
  new Paragraph({ spacing: { before: 600 }, children: [new TextRun({ text: "© 2026 Let Money Earn. All rights reserved.", size: 18, color: MUTED })] }),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: "Contents", bold: true, size: 36, font: SERIF })] }),
  new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }),
];

// ------------------------------------------------------------------ the book
// Introduction
body.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Introduction: the idea in one page")] }));
P("Most of us were taught one rule about the stock market: **buy low, sell high**. Momentum investing turns it on its head. It says: **buy what is already going up, and sell it once it stops.** Buy high, sell higher.");
P("That sounds like chasing. It is, a little. But it is chasing with rules. You don't buy a stock because it's on the news or because a friend made money on it. You buy it because, measured calmly, it has risen more strongly and more steadily than almost everything else, and you sell it the moment it no longer does.");
P(`Does it work? For more than a hundred years, traders have said yes. For the last thirty, academic research has agreed: in markets all over the world, stocks that have done well over the past several months tend to keep doing well for a while longer. This book tests the idea on Indian stocks, carefully and honestly. From ${fmonth(B.from)} to ${fmonth(B.to)}, a simple set of momentum rules on the Nifty 500 grew **₹1 lakh into about ${lakh(B.multiple)}**, or **${pct(B.cagr)} a year**. The Nifty 500 index grew ₹1 lakh into ${lakh(N.multiple)} (${pct(N.cagr)} a year) over the same period.`);
P("But the numbers are only half the story. The other half is what it feels like: the long months below your last high, the trades that lose, the times the rules sell right before the market bounces. A strategy only works if you can stick with it. So this book spends as much time on the pain as on the gain.");
callout("How to read this book.", "Chapters 1 to 3 explain what momentum is, where it came from and why it works. Chapters 4 to 9 describe our exact rules and put them through tough tests. Chapters 10 to 12 are practical: what holding it feels like, how to run it yourself, and the mistakes to avoid. Chapter 13 applies the same idea to ETFs. If you only have ten minutes, read this introduction, Chapter 6 and Chapter 12.");
figure("01_growth.png", `Growth of ₹1 with the momentum rules in this book, against the Nifty 500 index (${fmonth(B.from)} to ${fmonth(B.to)}). Log scale: equal percentage moves look the same size.`);

// Chapter 1
H1("1. What is momentum investing?");
P("Momentum is a word from physics: an object in motion tends to stay in motion. In investing it means the same thing. **A stock that has been rising tends to keep rising for a while, and a stock that has been falling tends to keep falling.** Not forever, and not every time, but often enough to build a strategy on.");
H2("A simple example");
P("Imagine two stocks, A and B. A year ago both were at ₹100. Today both are at about ₹172. On paper, both returned the same. But look at how they got there.");
figure("08_concept.png", "Two made-up stocks with the same one-year gain. A climbed steadily; B lurched up and down. A momentum investor prefers A.");
P("Stock A climbed in a fairly smooth line. Stock B jumped up, crashed, jumped again. A momentum investor prefers A. Its rise looks like **steady buying by many investors over many months**, the kind of trend that tends to continue. B's rise looks like luck and noise. That is why the strategy in this book doesn't just rank stocks by how much they rose; it ranks them by **how much they rose for each unit of bumpiness**. You'll see exactly how in Chapter 4.");
H2("Two kinds of momentum");
P("People use \"momentum\" for two related ideas. It helps to keep them apart:");
bullets([
  "**Relative momentum** (also called cross-sectional momentum): compare stocks with each other and buy the strongest. \"Of the 500 stocks in the Nifty 500, which 10 have been the best performers?\" This is how our strategy picks stocks.",
  "**Absolute momentum** (also called time-series momentum or trend-following): compare an asset with its own past. \"Is the market above or below where it has been on average over the last 200 days?\" This is how our strategy decides whether to be in the market at all.",
]);
P("Our rules use both. Relative momentum chooses **which** stocks to own. Absolute momentum on the Nifty 500 decides **whether** to own stocks at all, or to wait safely in a liquid fund.");
H2("How momentum differs from other styles");
table(["Style", "What it buys", "Why", "Typical holding"], [
  r_(["Value", "Cheap stocks (low price vs earnings, assets)", "The market will eventually notice they are cheap", "Years"]),
  r_(["Quality", "Strong, profitable, low-debt businesses", "Good businesses compound over time", "Years"]),
  r_(["Growth", "Companies growing sales and profits fast", "Growth will continue and lift the price", "Years"]),
  r_(["Momentum", "Stocks whose prices are already rising strongly", "Trends tend to persist for months", "Months"], true),
], { widths: [1.2, 3, 3.2, 1.3], leftCols: [1, 2], title: "Momentum compared with other investing styles." });
P("Momentum is the only one of these that looks mainly at the **price** rather than the business. That makes it simple and fully rule-based: no forecasting, no reading annual reports, no opinions. It also makes it quite different from the others, which is why many investors use it **alongside** a value or quality portfolio rather than instead of one.");
H2("What momentum is not");
bullets([
  "**It is not day trading.** Our strategy trades once a month, and a typical stock is held for about " + Math.round(T.medianHoldDays) + " days.",
  "**It is not buying tips or hot stocks.** Every buy and sell follows a written rule. Nothing is left to feel.",
  "**It is not a way to get rich quickly or safely.** It has had long losing stretches everywhere it has been studied. Chapter 10 covers them in detail.",
  "**It is not predicting the future.** The strategy never asks _why_ a stock is rising, or whether it _will_ rise. It only asks _whether it is rising now_, and reacts.",
]);

// Chapter 2
H1("2. A short history of momentum");
P("Momentum is not a new fad. Traders were using it a century ago, long before anyone could explain it. Academics ignored it for decades, then spent the last thirty years proving it and puzzling over why it works.");
H2("The traders (1900s to 1980s)");
bullets([
  "**Jesse Livermore (1900s to 1930s)** was one of the most famous speculators in American history. His story, told in the 1923 book _Reminiscences of a Stock Operator_ by Edwin Lefèvre, is full of momentum ideas: buy stocks that are making new highs, add to winners, cut losers quickly, and never argue with the market.",
  "**George Chestnutt (1930s to 1960s)** ran an American mutual fund using what he called relative strength: rank stocks and industries by how strongly they had risen, and own the leaders. He wrote that it is better to buy the leaders and leave the laggards alone.",
  "**Nicolas Darvas (1950s)**, a professional dancer, turned a small sum into about two million dollars by buying stocks breaking out to new highs and protecting himself with stop-losses. His 1960 book _How I Made $2,000,000 in the Stock Market_ is still widely read.",
  "**Robert Levy (1967)** published one of the first serious studies, _Relative Strength as a Criterion for Investment Selection_, in the _Journal of Finance_. He found that buying the strongest stocks beat the market. Many academics were unconvinced.",
  "**Richard Driehaus and William O'Neil (1980s)** made momentum mainstream among professional investors. Driehaus summed it up as \"buy high, sell higher\". O'Neil's CAN SLIM method, set out in his 1988 book _How to Make Money in Stocks_, includes \"L\" for Leader: buy the strongest stocks, not the laggards.",
]);
quote("It never was my thinking that made the big money for me. It always was my sitting.", "Jesse Livermore, in Reminiscences of a Stock Operator (1923)");
H2("The academics catch up (1990s onwards)");
P("For much of the 1970s and 1980s, finance professors believed markets were \"efficient\": prices already reflect all known information, so past prices can't predict future ones. Momentum should not exist. Then the evidence piled up.");
bullets([
  "**1993: Jegadeesh and Titman.** Narasimhan Jegadeesh and Sheridan Titman published _Returns to Buying Winners and Selling Losers_. Using US stocks from 1965 to 1989, they showed that buying the past 3 to 12 months' winners and selling the losers earned about 1% a month over the following months. This paper is the foundation of modern momentum research.",
  "**1997: Carhart.** Mark Carhart showed that much of what looked like mutual-fund managers' skill was really momentum. Momentum became a standard \"factor\", alongside market, size and value, in how professionals measure returns.",
  "**2012 to 2013: momentum everywhere.** Tobias Moskowitz, Yao Hua Ooi and Lasse Pedersen documented _time-series momentum_ across futures markets (stock indices, bonds, currencies, commodities). Clifford Asness, Moskowitz and Pedersen then showed in _Value and Momentum Everywhere_ that momentum works across countries and asset classes.",
  "**2016: two centuries of evidence.** Christopher Geczy and Mikhail Samonov rebuilt US stock data back to 1801 and found momentum in the 1800s too, long before anyone wrote about it.",
  "**2016: the crashes.** Kent Daniel and Tobias Moskowitz studied _momentum crashes_: rare, sudden periods when momentum loses very heavily, usually when a beaten-down market rebounds sharply (as in 1932 and 2009). This is momentum's biggest weakness, and a reason our rules include a market safety switch.",
]);
H2("Momentum in India");
P("Academic studies of Indian stocks have also found momentum effects, though Indian research has used shorter data histories than American studies. The idea became easy for ordinary investors to access when NSE Indices launched the **Nifty200 Momentum 30** index in 2020, with history calculated back to 2005. Since then, NSE has added other momentum indices, and many mutual funds have launched momentum index funds and ETFs that track them.");
P("Those funds are a simple way to get momentum exposure. The strategy in this book is different in a few ways: it looks at the wider Nifty 500, ranks stocks by return for each unit of risk, holds a concentrated 10 stocks, trades monthly, and steps out of the market entirely when the market is falling. Chapter 4 explains every rule.");
callout("Why a century of evidence matters.", "Any rule can look brilliant on a few years of data by luck. Momentum is different: it has been found in different centuries, countries and asset classes, by people who were trying to disprove it. That doesn't guarantee it will keep working, but it is far stronger evidence than a single good backtest.");

// Chapter 3
H1("3. Why does momentum work, and why doesn't everyone do it?");
P("If buying winners works so well, why hasn't everyone done it until the effect disappeared? There are two kinds of answers: human behaviour and risk.");
H2("Human behaviour");
bullets([
  "**We react slowly to news.** When a company's prospects improve, investors don't fully believe it at first. They wait for more proof. The price rises in steps as, one by one, investors catch up. Momentum rides that slow catching up.",
  "**We sell winners too early and hold losers too long.** Psychologists call this the _disposition effect_. Taking a profit feels good; selling at a loss feels like admitting a mistake. So winners are sold too soon (holding back their price rise) and losers are held too long (slowing their fall). The trends then play out over months instead of days.",
  "**We anchor to old prices.** \"It was ₹200 last year, it can't be worth ₹400.\" Anchoring makes investors hesitant to buy a stock that has already risen, so the rise continues more slowly than it \"should\".",
  "**We follow the crowd.** Once a trend is visible, it attracts more buyers: news coverage, fund managers who need to own the winners, retail investors. That extends the trend, sometimes too far.",
]);
H2("Risk");
P("Some researchers argue momentum's returns are payment for a real risk: **crashes**. Momentum strategies occasionally lose very heavily in a short time, usually when a falling market suddenly reverses and last year's losers shoot up. Investors who earn momentum's extra returns are, in this view, being paid to accept that rare but painful risk.");
H2("Why it hasn't been \"arbitraged away\"");
bullets([
  "**It is uncomfortable.** Momentum often means buying stocks that look expensive and selling ones that look cheap. It means long stretches of doing worse than the market. Most people give up at the worst moment.",
  "**It costs money to run.** The portfolio changes every month, so brokerage, taxes and price slippage eat into returns. Large funds can't trade small stocks without moving their prices.",
  "**Professional fund managers risk their jobs.** A manager who underperforms for two years may be fired, even if the strategy is sound. That career risk keeps many away.",
]);
callout("The honest summary.", "Momentum seems to work because people are people: slow to react, reluctant to sell losers, eager to follow the crowd. It stays profitable partly because it is hard to stick with. If you plan to use it, the most important skill is not picking stocks. It is sticking to the rules when it hurts.");
H2("Who momentum suits, and who it doesn't");
table(["It may suit you if…", "It may not suit you if…"], [
  r_(["You can follow written rules without second-guessing them", "You like to decide based on company stories or news"]),
  r_(["You can look at your portfolio once a day for a minute, and trade once a month", "You can't spare time each month-end to rebalance"]),
  r_([`You can live through a fall of ${pct(-B.maxDD, 0)} or more without selling in panic`, "A 25% fall in your portfolio would keep you awake at night"]),
  r_(["You are investing money you won't need for at least 5 years", "You may need this money in the next year or two"]),
  r_(["You accept that about half of your trades will lose money", "You need most of your trades to be winners to feel comfortable"]),
], { widths: [1, 1], leftCols: [1], title: "Is momentum right for you?" });

// Chapter 4
H1("4. The strategy tested in this book");
P("Here is the complete rule book. There is nothing hidden: anyone with a spreadsheet and price data can follow it.");
H2("The monthly routine");
steps([
  "**Start with the Nifty 500**, as the index stood at that time. (Why \"at that time\" matters so much is the subject of Chapter 5.)",
  "**Remove the weak and the illiquid.** A stock stays on the list only if (a) its price is within 25% of its all-time high, (b) it closes above its 233-day average price, a sign of a long-term uptrend, and (c) on average at least ₹1 crore of its shares change hands each day, so it is easy to buy and sell.",
  "**Score every remaining stock** by how strongly and smoothly it has risen (explained below).",
  "**Hold the top 10**, with equal money in each when bought.",
  "**Don't sell just for slipping a little.** A stock you hold is sold only when it falls out of the top 30, or fails one of the filters in step 2. This buffer avoids needless trading.",
  "**Trade once a month**, on the last trading day. Money from sold stocks is split equally among the new buys.",
]);
H2("The safety switch (checked every day)");
P("Every day, compare the Nifty 500 index with its **200-day moving average** (the average of its closing levels over the last 200 trading days, roughly the last ten months).");
bullets([
  "If the Nifty 500 **closes below its 200-day average three days in a row**, sell everything that day and move the money into a **liquid fund** (a low-risk debt mutual fund, assumed here to earn 6.5% a year).",
  "Stay in the liquid fund until a **month-end when the Nifty 500 is back above its 200-day average**. Then buy the top 10 again.",
]);
P("Why three days? One day below the average often turns out to be a false alarm. Three in a row is a clearer sign that the market's trend has turned. Chapter 8 compares this choice with others.");
H2("How the score works");
P("For each stock, we look at four periods: the last **252 trading days** (about 12 months), **184 days** (about 9 months), **126 days** (6 months) and **63 days** (3 months). For each period we calculate:");
body.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 120 },
  children: [new TextRun({ text: "Score for the period  =  % return over the period  ÷  annualised volatility", bold: true, size: 22, font: SERIF })] }));
P("**Volatility** measures how much the price jumps around from day to day. Annualised volatility of 30% means the stock's daily moves are typical of a stock that swings around 30% in a year. The final score is the **average of the four period scores**.");
table(["", "Stock A", "Stock B"], [
  r_(["Return over the last 12 months", "60%", "60%"]),
  r_(["Annualised volatility", "25%", "50%"]),
  r_(["12-month score (return ÷ volatility)", "2.4", "1.2"], true),
], { widths: [2.4, 1, 1], title: "An example: the same return, different scores." });
P("Both stocks returned 60%, but A did it with half the bumpiness, so it scores twice as high. Averaging four periods means a stock needs to have been strong over the long run **and** recently. A stock that shot up in the last month after a year of nothing won't rank near the top.");
H2("Why these particular rules?");
bullets([
  "**Near all-time high:** momentum is strongest in stocks close to their peaks. Stocks far below their highs often have a problem.",
  "**Above the 233-day average:** a basic check that the long-term trend is up. (In practice, as Chapter 7 shows, stocks strong enough to rank in the top 10 are almost always in an uptrend already.)",
  "**₹1 crore daily turnover:** avoids small, thinly traded stocks where buying and selling would move the price against you.",
  "**Ten stocks:** enough to spread risk, few enough to matter. Chapter 7 tests 5, 10, 15 and 20.",
  "**The top-30 buffer:** cuts trading roughly in half compared with selling anything that leaves the top 10, without hurting returns.",
]);
callout("A note on these rules.", "They were written down before this study. They come from a working spreadsheet scanner, not from searching past data for the best-looking settings. Chapter 7 then tests what happens when each rule is changed.");

// Chapter 5
H1("5. How we tested it honestly");
P("A **backtest** replays a strategy's rules on past prices to see what would have happened. It is the only way to test an idea without risking money, and also the easiest way to fool yourself. This chapter explains the traps and how the study avoided them.");
H2("Trap 1: using today's list of stocks for the past");
P("The easy way to test a Nifty 500 strategy is to download today's list of 500 stocks and test on their past prices. That quietly cheats. **Today's list contains the survivors**: companies that did well enough to be in the index now. Companies that crashed, went bankrupt, merged or were dropped from the index are missing. Testing only on survivors is like judging a school by the students who graduated and ignoring those who dropped out. This error is called **survivorship bias**.");
P(`To avoid it, the study rebuilt the real Nifty 500 list for each past date. NSE only publishes today's list, but the Wayback Machine (web.archive.org) has saved copies of NSE's own list file over the years. The study found ${SV.coverage.length} such lists from ${fmonth(SV.coverage[0].date)} to ${fmonth(SV.coverage[SV.coverage.length - 1].date)}. On each trading day, the backtest uses the latest list that existed on that day.`);
table(["Stock list", "CAGR", "Worst fall", "Sharpe"], [
  r_([SV.runs[0].label + " (biased)", pct(SV.runs[0].cagr), pct(SV.runs[0].maxDD), num(SV.runs[0].sharpe)]),
  r_([SV.runs[1].label + " (honest)", pct(SV.runs[1].cagr), pct(SV.runs[1].maxDD), num(SV.runs[1].sharpe)], true),
], { widths: [3.2, 1, 1, 1], title: "The same rules on biased and honest stock lists." });
figure("04_survivorship.png", "The same strategy, tested on today's list (biased) and on the list as it stood each month (honest).");
P(`The shortcut would have added about **${pts(SV.biasCagr).replace("+", "")} a year** to the result and made the worst fall look **${pts(SV.runs[0].maxDD - SV.runs[1].maxDD).replace("+", "")} smaller** than it really was. **Every number in this book uses the honest lists.** If you ever see a momentum backtest on Indian stocks that doesn't say how it handled this, treat it with suspicion.`);
H2("Trap 2: ignoring costs and taxes");
P("Every trade costs money: brokerage, Securities Transaction Tax (STT), stamp duty, exchange charges, GST, and the gap between buying and selling prices. The study charges **0.25% on every buy and every sell**. Chapter 9 shows results with higher costs, and after Indian capital-gains tax.");
H2("Trap 3: trying many rules and keeping the best");
P("If you test enough versions of a strategy, one will look great by luck. The study guards against this in three ways: the rules were fixed before testing; Chapter 7 shows that small changes to them give similar results; and it compares the strategy with 200 random copies to check that the ranking really adds value.");
H2("What the test can't do");
bullets([
  `**Six years is short.** The period (${fmonth(B.from)} to ${fmonth(B.to)}) was mostly a strong market for Indian stocks, with corrections in 2022 and 2024–25 but no crash like 2008 or March 2020.`,
  "**Some past members are missing.** A few companies that were in old Nifty 500 lists have no price history available (mostly merged or delisted ones). They are left out, so a small survivorship bias remains.",
  "**Gaps between archived lists.** No archived copy exists for some stretches (for example, July 2020 to May 2022). In those months the older list stays in use, so some index changes appear late.",
  "**Prices are adjusted for splits but not dividends**, for both the strategy and the index. Dividends would add a little to both.",
  "**Trades are assumed at the closing price.** Real trades may get slightly better or worse prices.",
]);

// Chapter 6
H1("6. The results");
H2("The headline numbers");
table(["", "Momentum strategy", "Nifty 500 index"], [
  r_(["Yearly growth (CAGR)", pct(B.cagr), pct(N.cagr)], true),
  r_(["₹1 lakh became", lakh(B.multiple), lakh(N.multiple)]),
  r_(["Worst fall from a high (max drawdown)", pct(B.maxDD), pct(N.maxDD)]),
  r_(["Volatility (bumpiness) per year", pct(B.vol), pct(N.vol)]),
  r_(["Sharpe ratio (return for the risk taken)", num(B.sharpe), num(N.sharpe)]),
  r_(["Trades", String(B.trades), "–"]),
  r_(["Share of trades that made money", pct(B.winRate, 0), "–"]),
], { widths: [2.6, 1.3, 1.3], title: `Results from ${fdate(B.from)} to ${fdate(B.to)}. Before tax, after 0.25% trading costs.` });
P(`Over about six years, the strategy grew money roughly **${num(B.multiple / N.multiple, 1)} times as much** as the Nifty 500. It also took more risk: its worst fall (${pct(B.maxDD)}) was deeper than the index's (${pct(N.maxDD)}), and its value jumped around more. The **Sharpe ratio** accounts for that: it measures return earned for each unit of bumpiness. The strategy's ${num(B.sharpe)} against the index's ${num(N.sharpe)} means it earned more even after allowing for its extra risk.`);
H2("Year by year");
figure("03_yearly.png", `Return in each calendar year. * ${years[0]} and ${years[years.length - 1]} are part-years.`);
table(["Year", "Momentum strategy", "Nifty 500", "Difference"], years.map(y => r_([y + (y === years[0] || y === years[years.length - 1] ? " (part)" : ""), pct(yr(y), 1, true), pct(yrN(y), 1, true), pts(yr(y) - yrN(y))])), { widths: [1, 1.3, 1.3, 1.3], title: "Returns by calendar year." });
P(`The best year was **${bestYear}** (${pct(yr(bestYear), 0, true)}), when strong stocks kept getting stronger. The worst was **${worstYear}** (${pct(yr(worstYear), 1, true)}), a year when the strategy lagged the index. This pattern is typical: momentum makes most of its money in a few big years and can have frustrating years in between.`);
H2("The falls");
figure("02_drawdown.png", "How far the strategy and the index were below their previous high at each point.");
table(["From a high on", "To a low on", "Fall", "Back to the high on"], R.drawdowns.slice(0, 5).map(d => r_([fdate(d.peak), fdate(d.trough), pct(d.depth), d.recovered ? fdate(d.recovered) : "not yet"])), { widths: [1.3, 1.3, 1, 1.4], title: "The five biggest falls." });
P(`The worst fall started in ${fmonth(R.drawdowns[0].peak)} and bottomed in ${fmonth(R.drawdowns[0].trough)}, ${Math.round(R.drawdowns[0].daysDown / 30)} months later, and ${R.drawdowns[0].recovered ? "recovered in " + fmonth(R.drawdowns[0].recovered) : "had not fully recovered by the end of the data"}. The safety switch moved to cash in January 2025, which stopped the fall from getting much deeper, but the portfolio still lost ground afterwards, both from the drop before the switch and from stocks that fell again after it re-entered.`);
H2("Month by month");
P(`Out of ${R.monthly.count} months, **${pct(R.monthly.positive, 0)} were positive** and the strategy beat the Nifty 500 in ${pct(R.monthly.beatNifty, 0)} of them. The best month gained ${pct(R.monthly.best, 1, true)} and the worst lost ${pct(R.monthly.worst, 1)}. Some of the \"positive\" months were spent quietly in the liquid fund.`);
H2("The trades");
P(`The strategy made ${T.count} completed trades. **Only ${pct(T.winRate, 0)} made money**, not much better than a coin flip. But the average winning trade gained **${pct(T.avgWin, 0, true)}**, while the average losing trade lost only **${pct(T.avgLoss, 0)}**. Winners were about **${num(T.payoff, 1)} times bigger** than losers. The five best trades alone made ${pct(T.top5ShareOfGains, 0)} of all profits.`);
table(["Best trades", "Bought", "Sold", "Return"], T.best.map(t => r_([t.symbol, fmonth(t.entry), fmonth(t.exit), pct(t.ret, 0, true)])), { widths: [1.6, 1, 1, 1], title: "The five best trades." });
table(["Worst trades", "Bought", "Sold", "Return"], T.worst.map(t => r_([t.symbol, fmonth(t.entry), fmonth(t.exit), pct(t.ret, 0)])), { widths: [1.6, 1, 1, 1], title: "The five worst trades." });
callout("This is the heart of momentum.", "You will be wrong about half the time. The strategy makes money because it cuts losers quickly (they drop out of the ranking) and lets winners run for as long as they stay strong. Anyone who sells winners early to \"lock in profits\", or holds losers hoping they come back, breaks the one thing that makes it work.");

// Chapter 7
H1("7. Stress tests: is it real?");
P("A good-looking backtest proves little by itself. This chapter asks four hard questions.");
H2("Test 1: skill or luck?");
P(`The study ran **${L.runs} copies** of the strategy with the same filters, costs and safety switch, but picking stocks **at random** from those that passed the filters instead of using the ranking. If the ranking were worthless, the real strategy would land in the middle of the random copies.`);
figure("05_luck.png", "Yearly returns of 200 random copies (grey bars) and the real strategy (red line).");
P(`The random copies earned a median **${pct(L.percentiles["50"])}** a year (the middle 90% ranged from ${pct(L.percentiles["5"])} to ${pct(L.percentiles["95"])}). The real strategy earned ${pct(B.cagr)} and beat **${Math.round(L.shareBeaten * L.runs)} of the ${L.runs}**. The ranking adds real value. Notice too that the random copies beat the Nifty 500 (${pct(N.cagr)}) on their own: the filters and the safety switch help even without the ranking.`);
H2("Test 2: does it depend on one lucky setting?");
P("If only the exact original settings worked, the result would probably be a fluke of fitting the past. Here each rule is changed while everything else stays the same.");
const pick = [
  ["Stocks held (top N)", "Top 5", "Hold 5 stocks instead of 10"], ["Stocks held (top N)", "Top 15", "Hold 15 stocks"], ["Stocks held (top N)", "Top 20", "Hold 20 stocks"],
  ["Exit rank", "Sell when out of top 10", "Sell when out of the top 10 (no buffer)"], ["Exit rank", "Sell when out of top 50", "Sell when out of the top 50"],
  ["Lookbacks", "12 months only", "Score on 12 months only"], ["Lookbacks", "6 months only", "Score on 6 months only"],
  ["Near all-time high", "Within 15%", "Must be within 15% of all-time high"], ["Near all-time high", "No ATH filter", "No all-time-high filter"],
  ["Trend filter", "No trend filter", "No 233-day trend filter"], ["Rebalance frequency", "Quarterly", "Trade every 3 months, not monthly"],
];
table(["Change", "CAGR", "Worst fall", "Sharpe"], [
  r_(["Our rules, unchanged", pct(B.cagr), pct(B.maxDD), num(B.sharpe)], true),
  ...pick.map(([g, l, label]) => { const x = row(g, l); return r_([label, pct(x.cagr), pct(x.maxDD), num(x.sharpe)]); }),
], { widths: [3, 1, 1, 1], title: "One rule changed at a time, everything else the same." });
bullets([
  `**Most changes move the result by a few points, not tens.** That is a good sign: the strategy isn't balanced on a knife-edge.`,
  `**Holding more stocks cut the falls.** With 15 or 20 stocks, the worst fall was ${pct(row("Stocks held", "Top 15").maxDD)} and ${pct(row("Stocks held", "Top 20").maxDD)}, against ${pct(B.maxDD)} with 10. Returns were similar. If you prefer a smoother ride, holding 15 to 20 is a sensible choice.`,
  `**Trading only every three months was clearly worse** (${pct(row("Rebalance", "Quarterly").cagr)} a year). Momentum fades; the portfolio needs refreshing monthly.`,
  `**The trend filter never changed anything**, because stocks strong enough to reach the top 10 are almost always in an uptrend anyway.`,
]);
H3("How many stocks to hold vs. when to sell");
const ns = [5, 10, 15, 20], ks = [10, 20, 30, 50];
table(["", ...ks.map(k => "Sell when out of top " + k)], ns.map(n => r_(["Hold top " + n, ...ks.map(k => { const g = cell(pitGrid, n, k); return g ? `${pct(g.cagr)} (${pct(g.maxDD, 0)})` : "–"; })], n === 10)), { widths: [1.2, 1, 1, 1, 1], title: "Yearly return (and worst fall) for each combination." });
P("Every combination made money, and none depends on luck of one setting. Holding more stocks consistently reduced the worst fall. Selling sooner (\"out of top 10\") did not help and meant much more trading.");
H2("Test 3: was the trading day lucky?");
table(["Trade on", "CAGR", "Worst fall", "Sharpe"], S.timing.map(t => r_([t.label.replace("(base)", "(our rule)"), pct(t.cagr), pct(t.maxDD), num(t.sharpe)], t.label.includes("base"))), { widths: [2.4, 1, 1, 1], title: "The same strategy traded on different days of the month." });
P(`Whichever day you trade, the strategy works, earning ${pct(Math.min(...S.timing.map(t => t.cagr)))} to ${pct(Math.max(...S.timing.map(t => t.cagr)))} a year. But the month-end day used in this book happened to be the best of these, so **expect a couple of points less** in real life. It's honest to plan for that.`);
H2("Test 4: survivorship bias");
P(`Covered in Chapter 5: the honest lists cost about ${pts(SV.biasCagr).replace("+", "")} a year compared with using today's list, and every number in this book already includes that.`);

// Chapter 8
H1("8. The safety switch: getting out of the way");
P("Momentum's biggest danger is a falling market. When the whole market drops, yesterday's winners often drop hardest. The safety switch is designed to step aside during those periods and wait in a liquid fund.");
figure("06_switch.png", "The Nifty 500, its 200-day average, and the periods the strategy spent in the liquid fund (shaded).");
H2("Every time the switch moved to cash");
table(["Sold everything on", "Bought back on", "Nifty 500 meanwhile", "Liquid fund"], G.spells.map(s => r_([fdate(s.from), s.to ? fdate(s.to) : "still out", pct(s.nifty500, 1, true), pct(s.liquid, 1, true)])), { widths: [1.3, 1.3, 1.3, 1.1], title: "The strategy's periods in the liquid fund." });
P("In this period the switch often stepped out just before the market steadied, so the index was slightly higher by the time the strategy bought back. That is the price of insurance: most of the time it costs a little. It pays off in a long, deep fall, which this six-year period didn't have. The 2008 crash, when Indian stocks fell by more than half, is the kind of event the switch is designed for.");
H2("Checking daily vs. once a month");
table(["Market check", "CAGR", "Worst fall", "Sharpe"], [
  "200-DMA, checked at month-end only", "200-DMA, exit after 1 close below", "200-DMA, exit after 2 closes", "200-DMA, exit after 3 closes", "200-DMA, exit after 5 closes", "No market filter",
].map(l => { const x = row("Market filter", l); return r_([x.label.replace("(base)", "(our rule)").replace("No market filter (always invested)", "No safety switch (always invested)"), pct(x.cagr), pct(x.maxDD), num(x.sharpe)], x.isBase); }), { widths: [3.2, 1, 1, 1], title: "How quickly the safety switch reacts." });
P(`Checking the market only at month-end meant waiting up to a month while the market fell. Checking daily and acting after **three closes in a row** below the average cut the worst fall from ${pct(monthly.maxDD)} to ${pct(B.maxDD)}, and lifted the return from ${pct(monthly.cagr)} to ${pct(B.cagr)}. Acting after just one day meant more false alarms. Two or three days worked best, but with so few exits in six years, don't read too much into the exact number.`);
H2("Which moving average?");
P("A shorter average follows the market closely and reacts to small dips. A longer one moves slowly and only reacts to bigger falls. Here is the same strategy with four different averages behind the switch.");
table(["Safety switch", "CAGR", "Worst fall", "Sharpe", "Times sold out", "Time invested", "After tax"], M.rows.map(r => r_([`${r.ma}-day average${r.isBase ? " (our rule)" : ""}`, pct(r.cagr), pct(r.maxDD), num(r.sharpe), String(r.exits), pct(r.invested, 0), pct(r.afterTax)], r.isBase)), { widths: [2.2, 0.9, 0.9, 0.8, 1, 1, 0.9], title: "The safety switch with different moving averages." });
figure("07_moving_averages.png", "Growth of ₹1 with each moving average behind the safety switch.");
bullets([
  `**If you want the higher return and can sit through a fall of about ${pct(-B.maxDD, 0)}:** keep the **200-day average**. It sold out only ${ma(200).exits} times and stayed invested ${pct(ma(200).invested, 0)} of the time, so it caught the big rallies. (The 150-day did slightly better here, ${pct(ma(150).cagr)}, but with a deeper fall of ${pct(ma(150).maxDD)}; a gap that small is within luck.)`,
  `**If you want smaller falls and can give up a little return:** the **100-day average** kept the worst fall to ${pct(ma(100).maxDD)} while earning ${pct(ma(100).cagr)} a year.`,
  `**The 50-day average isn't worth it:** it sold out ${ma(50).exits} times, spent ${pct(1 - ma(50).invested, 0)} of the time in cash, missed much of the big rallies, and earned ${pct(ma(50).afterTax)} after tax against ${pct(ma(200).afterTax)} for the 200-day.`,
]);
callout("Be honest with yourself.", `The best rule is the one you will actually follow. If watching a quarter of your money disappear on paper would make you sell, choose the 100-day average. You'll give up a little return, but you're far more likely to stay the course.`);
H2("Should the waiting money go into gold?");
P(`Instead of a liquid fund, the study tried parking the money in GOLDBEES, a gold ETF, whenever the switch said stay out. Gold added ${pts(pitGold.cells[1].cagr - pitGold.cells[0].cagr).replace("+", "")} a year, but the ride got bumpier (volatility ${pct(pitGold.cells[1].vol)} vs ${pct(pitGold.cells[0].vol)}) and the Sharpe ratio fell from ${num(pitGold.cells[0].sharpe)} to ${num(pitGold.cells[1].sharpe)}. Nearly all of the gain came from one spell in early 2025, when gold rallied sharply. In another spell (2026), gold fell while the liquid fund kept earning. **The liquid fund's job is to keep money safe while you wait. Gold turns the wait into a second bet.**`);
H2("Would a stop-loss help?");
P(`A stop-loss sells a stock as soon as it falls, say, 10% during the month. It sounds sensible. It didn't help. On the honest lists, a 10% stop cut the return from ${pct(pitStop.cells[0].cagr)} to ${pct(pitStop.cells[1].cagr)} a year. When the stop sold a stock, it had bounced back by the next month-end ${pct(SL.afterStop.rebounded, 0)} of the time: a 10% dip in a strong stock is usually just noise. Adding a stop on top of the safety switch cut the return to ${pct(mf.dailyPlusStop.cagr)}. **To limit losses, the market safety switch works; individual stop-losses mostly add trades and costs.**`);

// Chapter 9
H1("9. Costs, tax and how much money it can handle");
H2("Trading costs");
table(["Cost on each buy and sell", "CAGR", "Worst fall", "Sharpe"], S.costs.rows.map(r => r_([r.label.replace(" per side", "") + (r.label.startsWith("0.25") ? " (used in this book)" : ""), pct(r.cagr), pct(r.maxDD), num(r.sharpe)], r.label.startsWith("0.25"))), { widths: [2.4, 1, 1, 1], title: "The effect of trading costs." });
P("Costs matter because the portfolio turns over about " + num(B.turnoverPerYear, 1) + " times a year. With a discount broker, total costs (brokerage, STT, stamp duty, exchange fees, GST, and the buy-sell price gap) for liquid Nifty 500 stocks are usually around 0.2% to 0.3% per trade. Keep them low: avoid brokers who charge a percentage of trade value.");
H2("Tax");
P(`Profits on shares held for under a year are **short-term capital gains**, taxed at 20% (15% before 23 July 2024). Held for a year or more, they are **long-term**, taxed at 12.5% above an exemption limit (10% before 23 July 2024). Losses can be set off against gains. Because a typical stock is held for about ${Math.round(T.medianHoldDays)} days, most profits here are short-term.`);
table(["", "CAGR"], [r_(["Before tax", pct(S.costs.preTax.cagr)]), r_(["After capital-gains tax", pct(S.costs.afterTax.cagr)], true)], { widths: [3, 1], title: "Tax applied to every profit, year by year." });
P(`Tax took about ${pts(S.costs.preTax.cagr - S.costs.afterTax.cagr).replace("+", "")} a year. The study slightly overstates tax for small accounts, because it ignores the yearly long-term gains exemption. Tax rules change; check the current rules or ask a tax adviser.`);
H2("How much money can it handle?");
P("A large buy order in a small stock pushes its price up before you finish buying. The study compares each purchase with how much of that stock normally trades in a day.");
table(["Starting capital", "Typical buy as % of a day's trading", "Buys over 10% of a day's trading"], S.capacity.map(c => r_([c.capital >= 1e7 ? "₹" + c.capital / 1e7 + " crore" : "₹" + c.capital / 1e5 + " lakh", pct(c.medianShareOfAdv, 1), pct(c.over10pct, 0)])), { widths: [1.4, 1.6, 1.6], title: "Each buy compared with the stock's normal daily trading." });
P(`Buying more than about 10% of a day's trading is hard without moving the price. Up to about **₹10 crore**, the buys are small next to these stocks' daily trading. At **₹100 crore**, ${pct(cap(1e9).over10pct, 0)} of buys would be too big. For individual investors, size is not a problem.`);

// Chapter 10
H1("10. What it feels like to hold");
P("Backtest charts go up and to the right. Living through them doesn't feel that way. This chapter is about the experience, because that is what decides whether you earn the returns.");
H2("You will spend most of your time below your last high");
P(`The strategy was below its previous high on **${pct(R.timeUnderwater, 0)} of trading days**. Most of the time, you will be looking at a portfolio worth less than it once was. New highs arrive in bursts, often after long waits. That is normal for any growth investment, and especially for momentum.`);
H2("You will be wrong half the time");
P(`About ${pct(1 - T.winRate, 0)} of trades lose money. Some lose ${pct(-T.worst[0].ret, 0)} or more. You'll buy a stock at the top of the rankings and watch it fall the next month. Each individual trade will often feel like a mistake. Only the whole collection of trades works.`);
H2("You will look foolish sometimes");
bullets([
  "The safety switch will sell everything, and the market will rise the next week. It happened several times in this study.",
  `Your portfolio will lag the index for a whole year, as it did in ${worstYear}, while friends in index funds or \"safe\" stocks do better.`,
  "You will own stocks that everyone says are overpriced, and sell stocks that look cheap.",
]);
callout("The one thing to remember.", "Most people who give up on a strategy give up near the bottom, right before it recovers. Decide now, while you are calm, what you will do when the portfolio is down 25%. Write it down. The answer should be: follow the rules.");
H2("Eggs in one basket");
P(`No rule limits how much goes into one industry. On average the biggest industry made up **${pct(R.industry.avgMaxIndustryWeight, 0)}** of the portfolio, and at one point **${pct(R.industry.peakIndustryWeight, 0)}**. When a sector is hot, momentum piles into it. That boosts returns in a boom and hurts in a bust.`);
table(["Industry", "Average share of the portfolio"], R.industry.avgWeights.map(w => r_([w.industry, pct(w.weight, 0)])), { widths: [3, 1.4], title: "Average share of the portfolio by industry." });

// Chapter 11
H1("11. How to run it yourself");
H2("What you need");
bullets([
  "**A demat and trading account** with a low-cost broker.",
  "**Price data** for Nifty 500 stocks: a spreadsheet with Google Finance or a similar source, a stock screener that can calculate returns and volatility, or a small script.",
  "**The current Nifty 500 list**, downloadable free from the NSE Indices website. Update it whenever NSE rebalances the index (usually in March and September).",
  "**A liquid fund** in the same account or folio, to park money when the safety switch is off.",
  "**About an hour at each month-end**, and a minute each trading day to check the market.",
]);
H2("Every trading day (one minute)");
steps([
  "Look up the Nifty 500's closing level and its 200-day average.",
  "Count how many days in a row it has closed below the average.",
  "If it's the **third close in a row below**, sell all your stocks and move the money into the liquid fund.",
]);
H2("Every month-end (about an hour)");
steps([
  "**Check the market.** If the Nifty 500 is below its 200-day average and you are in the liquid fund, do nothing: stay out until a month-end when it's above.",
  "**Update the list and prices.** Use the current Nifty 500 list.",
  "**Filter.** Keep stocks within 25% of their all-time high, above their 233-day average, and trading at least ₹1 crore a day.",
  "**Score and rank** what's left, highest score first.",
  "**Sell** any stock you hold that is now outside the top 30 or fails a filter.",
  "**Buy** the highest-ranked stocks you don't already own until you hold 10, splitting the money from sales (or from the liquid fund) equally.",
  "**Record everything**: date, stock, price, quantity, reason. You'll need it for tax, and for staying honest with yourself.",
]);
H2("A worked example: September 2026");
P(`At the time of writing, the Nifty 500 closed at ${Math.round(X.now.nifty).toLocaleString("en-IN")} on ${fdate(X.now.date)}, below its 200-day average of ${Math.round(X.now.sma).toLocaleString("en-IN")}. It first closed below the average in early September and stayed there. Under the rules in this book, the third close below (${fdate(G.spells[G.spells.length - 1].from)}) was the signal to sell everything and move to the liquid fund. The strategy then waits for a month-end with the Nifty 500 back above its average before buying again.`);
H2("Practical tips");
bullets([
  "**Start with money you won't need for five years or more.** Momentum can take years to pay off.",
  "**Don't put everything into one strategy.** Many investors keep momentum as one part of their portfolio, next to index funds or longer-term holdings.",
  "**Round sensibly.** If a share is too expensive to split money exactly equally, get as close as you can; small differences don't matter.",
  "**Never override the rules for one stock.** \"I'll keep this one, I like the company\" is how a rule-based strategy quietly becomes a feeling-based one.",
  "**Review once a year, not once a week.** Judge the strategy over years, not months.",
]);

// Chapter 12
H1("12. Common mistakes, and questions people ask");
H2("Mistakes to avoid");
table(["Mistake", "Why it hurts"], [
  r_(["Selling winners early to \"book profit\"", "The big winners pay for all the losers. Cutting them short removes the engine."]),
  r_(["Holding losers \"until they come back\"", "Falling stocks tend to keep falling. The ranking sells them for a reason."]),
  r_(["Skipping the safety switch because \"this time is different\"", "The switch exists for the rare, deep crash. You can't know in advance which fall will be the big one."]),
  r_(["Quitting after a bad year", "Every momentum strategy has bad years. Quitting locks in the loss and misses the recovery."]),
  r_(["Testing on today's stock list", "Survivorship bias makes a strategy look better and safer than it is (Chapter 5)."]),
  r_(["Tweaking the rules after every bad month", "Constant changes mean you never follow any strategy long enough for it to work."]),
  r_(["Ignoring costs and tax", "At about 2.4 portfolio turns a year, small costs add up quickly."]),
], { widths: [1.4, 2.6], leftCols: [1], title: "Common momentum mistakes." });
H2("Questions people ask");
const faq = [
  ["Isn't this just chasing stocks that have already gone up?", "Yes, deliberately, but with rules. The evidence over a century is that stocks rising strongly and steadily tend to keep rising for months. The rules also make you sell when they stop, which casual chasing never does."],
  ["Why not just buy a momentum index fund?", "That's a perfectly good, simpler option. Index funds handle the rebalancing for you. The strategy in this book differs in its stock universe, scoring, number of stocks, and especially its safety switch, which index funds don't have."],
  ["Will I really earn " + pct(B.cagr, 0) + " a year?", "Almost certainly not exactly. That figure comes from one six-year period that was good for Indian stocks, before tax, and with the luckiest trading day. Expect lower returns, and deeper falls, in real life. What the study shows is that the approach worked across many settings and beat random stock picking, not that the future will match the past."],
  ["What if the market crashes like 2008?", "The safety switch would sell after three closes below the 200-day average. It wouldn't avoid the first part of the fall, but it is designed to avoid most of a long, deep decline. This six-year period had no such crash, so the switch's value in one wasn't tested here."],
  ["Can I use this for mid-caps or small-caps only?", "You can, but smaller stocks are harder to trade, and their past index lists are harder to get, so testing them honestly is difficult. This study only used the Nifty 500 because past lists could be rebuilt."],
  ["How much money do I need to start?", "Enough to buy 10 stocks in sensible amounts, so that brokerage and other fixed costs stay small. There's no upper limit for individuals: the strategy handled up to about ₹10 crore comfortably."],
  ["What would make me stop using it?", "Decide in advance. A sensible rule: don't judge it on less than three years. Stop only if you find a mistake in how you are running it, or if your own situation changes, not because of one bad year."],
];
faq.forEach(([q, a]) => { H3(q); P(a); });

// Appendix
// Chapter 13: ETFs
{
  const es = E.stats[0], en = E.stats[1], eg = E.stats[2], eb = E.base, et = E.trades, sl = E.sinceAllListed;
  const eyears = Object.keys(E.yearly.strategy);
  const WHAT = {
    AUTOBEES: "Auto companies (Nifty Auto)", CPSEETF: "Central public-sector companies (Nifty CPSE)", FMCGIETF: "Consumer goods companies (Nifty FMCG)",
    GOLDBEES: "Gold", HEALTHY: "Healthcare companies", INFRAIETF: "Infrastructure companies (Nifty Infrastructure)",
    LTGILTBEES: "Long-term government bonds", METALIETF: "Metal companies (Nifty Metal)", MODEFENCE: "Defence companies (Nifty India Defence)",
    MOREALTY: "Real-estate companies (Nifty Realty)", NIFTYBEES: "India's 50 largest companies (Nifty 50)", PHARMABEES: "Pharma companies (Nifty Pharma)",
    PSUBNKBEES: "Public-sector banks (Nifty PSU Bank)", PVTBANIETF: "Private-sector banks (Nifty Private Bank)", SILVERBEES: "Silver",
  };
  const sensE = (g, l) => E.sensitivity[g].find(r => r.label.startsWith(l));
  const never = Object.keys(E.listed).filter(k => !E.monthsHeld[k]);
  const lastLeft = Object.fromEntries(E.log[E.log.length - 1].left.map(x => [x.s, x.why]));
  const closedE = E.trades.list.filter(t => t.out);
  const bestE = [...closedE].sort((a, b) => b.ret - a.ret).slice(0, 5);
  const yrsE = (new Date(es.to) - new Date(es.from)) / 3.15576e10, yrsS = (new Date(B.to) - new Date(B.from)) / 3.15576e10;

  H1("13. Momentum with ETFs");
  P("Everything so far has been about individual stocks. The same idea works with **exchange-traded funds (ETFs)**: funds that trade on the exchange like a share and track an index, a sector, or a commodity such as gold. Instead of picking the 10 strongest stocks, you pick the strongest few ETFs, and let the rotation move between Indian shares, sectors, gold, silver and government bonds.");
  H2("Why use ETFs?");
  bullets([
    "**They can't go bust.** An ETF holds a whole basket. A single company can collapse; a Nifty 50 ETF can't vanish overnight.",
    "**They are already diversified**, so you need only a handful of holdings instead of ten or more stocks.",
    "**They cover more than shares.** Gold, silver and government-bond ETFs let the rotation step away from equities when shares are weak, without a separate market switch.",
    "**Trading is cheap and rare.** ETFs have low costs, and the rotation in this chapter changed its holdings only a couple of times a year.",
    "**The drawbacks:** fewer choices, many sector ETFs are only a few years old, and some trade thinly.",
  ]);
  H2("The ETFs tested");
  table(["ETF", "What it tracks", "Trading since"], [...Object.keys(E.listed).sort().map(k => r_([k, WHAT[k] || "", fmonth(E.listed[k])])), r_(["LIQUIDCASE", "Overnight money-market rates (used as cash)", "Jan 2024"])],
    { widths: [1.2, 3, 1.1], leftCols: [1], title: "The 16 ETFs in the rotation." });
  P("An ETF only enters the ranking once it has traded for about a year (the score needs a year of prices). So the list grew over time, exactly as it did for a real investor: in 2017 only NIFTYBEES, GOLDBEES, CPSEETF and PSUBNKBEES were eligible; the full list was only available from late 2025.");
  H2("The rules");
  table(["", "Stock strategy (Chapters 4 to 9)", "ETF rotation"], [
    r_(["Universe", "Nifty 500, as it stood each month", `The ${Object.keys(E.listed).length} ETFs above, once each had a year of prices`]),
    r_(["Score and filters", "Return ÷ volatility; near all-time high, above 233-day average, ₹1 crore turnover", "The same"]),
    r_(["Holdings", "Top 10", `Top ${eb.top_n}, each a 1/${eb.top_n} slot`]),
    r_(["When to sell", "Out of the top 30, or fails a filter", `Out of the top ${eb.exit_rank}, or fails a filter`]),
    r_(["Market safety switch", "Yes: 3 closes below the Nifty 500's 200-day average", "None: gold, bonds and cash take over on their own"]),
    r_(["Waiting money", "Liquid fund", "LIQUIDCASE (6.5% a year assumed before it existed)"]),
    r_(["Costs", "0.25% per trade", "0.25% per trade"]),
  ], { widths: [1.3, 2.3, 2.3], leftCols: [1, 2], title: "Stock strategy and ETF rotation, side by side." });
  H2("The results");
  table(["", "CAGR", "Worst fall", "Volatility", "Sharpe", "₹1 lakh became"], E.stats.map((x, i) => r_([x.label, pct(x.cagr), pct(x.maxDD), pct(x.vol), num(x.sharpe), lakh(x.multiple)], i === 0)),
    { widths: [2.4, 0.9, 0.9, 0.9, 0.8, 1.2], title: `ETF rotation from ${fdate(es.from)} to ${fdate(es.to)}. Before tax, after costs.` });
  figure("09_etf_growth.png", "Growth of ₹1 with the ETF rotation, against simply holding NIFTYBEES or GOLDBEES.");
  P(`The rotation earned **${pct(es.cagr)} a year** with a worst fall of only **${pct(es.maxDD)}** and volatility of ${pct(es.vol)}, lower than even the Nifty's. NIFTYBEES earned ${pct(en.cagr)} with a worst fall of ${pct(en.maxDD)} (the March 2020 crash). Simply holding **GOLDBEES earned ${pct(eg.cagr)}**, a little more than the rotation, because these were exceptional years for gold. The rotation's advantage is that it doesn't depend on gold continuing: it moves on when gold stops rising.`);
  P(`Its early years were quiet, because only a few ETFs existed and money often sat in cash (${pct(E.avgCash, 0)} on average over the whole period). Since all the ETFs were trading (${fmonth(sl.from)}), it earned **${pct(sl.strategy.cagr)} a year** while NIFTYBEES earned ${pct(sl.nifty.cagr)}.`);
  table(["Year", "ETF rotation", "NIFTYBEES", "GOLDBEES"], eyears.map(y => r_([y + (y === eyears[0] || y === eyears[eyears.length - 1] ? " (part)" : ""), pct(E.yearly.strategy[y], 1, true), pct(E.yearly.nifty[y], 1, true), pct(E.yearly.gold[y], 1, true)])),
    { widths: [1, 1.2, 1.2, 1.2], title: "Returns by calendar year." });
  H2("What it held");
  figure("10_etf_held.png", `Months each ETF spent in the portfolio, out of ${E.months}.`);
  P(`Gold and the Nifty were the backbone, joined by PSU banks and CPSE companies during their long rally, and by silver, bonds, pharma and metals more recently. ${never.join(", ")} were never picked. At the last month-end, for example: ${never.map(k => `${k}: ${(lastLeft[k] || "ranked below the top " + eb.top_n).toLowerCase()}`).join("; ")}.`);
  P(`There were only **${et.count} completed trades**, and **${pct(et.winRate, 0)} made money**. The average winner gained ${pct(et.avgWin, 0, true)}, the average loser lost just ${pct(et.avgLoss, 0)}, and a typical ETF was held for about ${Math.round(et.medianDays / 30)} months.`);
  table(["Best trades", "Bought", "Sold", "Return"], bestE.map(t => r_([t.s, fmonth(t.in), fmonth(t.out), pct(t.ret, 0, true)])), { widths: [1.6, 1, 1, 1], title: "The five best ETF trades." });
  H2("Does it depend on the settings?");
  table(["Change", "CAGR", "Worst fall", "Sharpe"], [
    ...E.sensitivity["ETFs held"].map(r => r_([`Hold ${r.label.replace(" (base)", "").replace("Top", "top")}${r.label.includes("base") ? " (our rule)" : ""}`, pct(r.cagr), pct(r.maxDD), num(r.sharpe)], r.label.includes("base"))),
    r_(["No filters at all", pct(sensE("Filters", "No filters").cagr), pct(sensE("Filters", "No filters").maxDD), num(sensE("Filters", "No filters").sharpe)]),
    r_(["No 233-day trend filter", pct(sensE("Filters", "No 233").cagr), pct(sensE("Filters", "No 233").maxDD), num(sensE("Filters", "No 233").sharpe)]),
    r_(["Add a NIFTYBEES market switch", pct(E.sensitivity["Market switch"][1].cagr), pct(E.sensitivity["Market switch"][1].maxDD), num(E.sensitivity["Market switch"][1].sharpe)]),
  ], { widths: [2.6, 1, 1, 1], title: "The ETF rotation with one setting changed." });
  bullets([
    "**Fewer ETFs, bigger swings.** Holding 2 or 3 earned more but fell harder; holding 7 was smoother but earned less. Five is a sensible middle.",
    "**The filters matter.** Without them the return dropped and the falls deepened. The trend filter did most of the work.",
    "**No market switch needed.** Adding one lowered the return: with gold, bonds and cash on the list, the rotation already steps away from falling shares.",
    "**When to sell and trading costs barely mattered**, because the rotation trades so rarely.",
  ]);
  H2("Stocks or ETFs?");
  table(["", "Stock strategy", "ETF rotation"], [
    r_(["Period tested", `${fmonth(B.from)} to ${fmonth(B.to)} (${yrsS.toFixed(1)} years)`, `${fmonth(es.from)} to ${fmonth(es.to)} (${yrsE.toFixed(1)} years)`]),
    r_(["Yearly growth (CAGR)", pct(B.cagr), pct(es.cagr)]),
    r_(["Worst fall", pct(B.maxDD), pct(es.maxDD)]),
    r_(["Volatility", pct(B.vol), pct(es.vol)]),
    r_(["Sharpe", num(B.sharpe), num(es.sharpe)]),
    r_(["Completed trades", String(B.trades), String(et.count)]),
    r_(["Holdings", "10 stocks", `${eb.top_n} ETFs`]),
    r_(["Main risk", "Deep falls in small and mid caps", "Depends heavily on gold; few ETFs in early years"]),
  ], { widths: [1.6, 2, 2], leftCols: [1, 2], title: "The two approaches compared. The periods differ, so compare the character, not the exact numbers." });
  P("The stock strategy aims for higher returns and asks you to sit through deeper falls. The ETF rotation is gentler: fewer holdings, far fewer trades, smaller falls, and it can hold gold and bonds when shares are weak. Many investors could reasonably use the ETF rotation on its own, or run both side by side.");
  callout("Be careful with this result.", "The ETF list was chosen today, with some knowledge of which themes did well, and no ETF that closed down in the past can appear in it. Until 2021 only a handful of ETFs were eligible. And these were exceptional years for gold and, in 2025, silver. Treat the ETF numbers as more flattering, and less certain, than the stock study's.");
}

H1("Appendix A: Glossary");
table(["Term", "Meaning"], [
  ["Backtest", "Running a strategy's rules on past prices to see what would have happened. Hypothetical, not real trading."],
  ["CAGR", "Compound annual growth rate: the average yearly growth. 20% means money grew by about a fifth each year."],
  ["Drawdown", "A fall from a previous high. Max drawdown is the biggest such fall."],
  ["Volatility", "How much a price jumps around, usually stated per year. Higher volatility means a bumpier ride."],
  ["Sharpe ratio", "Return above a safe rate (here 6.5%), divided by volatility. Higher is better; above 1 is good."],
  ["Calmar ratio", "Yearly return divided by the worst fall. More return per rupee of pain."],
  ["Moving average", "The average closing price over a set number of recent days, such as 200."],
  ["Liquid fund", "A mutual fund that invests in very short-term, low-risk debt. Used as a safe place to wait."],
  ["Survivorship bias", "The error of testing only on things that survived to today, ignoring failures."],
  ["Point-in-time list", "The list of index members as it actually stood on a past date."],
  ["Turnover", "How much of the portfolio is replaced in a year. 2× means every stock is swapped about twice."],
  ["Rebalance", "The monthly routine of selling and buying to bring the portfolio back in line with the rules."],
].map(r => r_(r)), { widths: [1.2, 3.8], leftCols: [1] });

H1("Appendix B: Data and method");
bullets([
  `**Period:** ${fdate(B.from)} to ${fdate(B.to)}.`,
  `**Stocks:** Nifty 500 members on the most recent archived NSE list dated on or before each trading day (${SV.coverage.length} lists). Past members without price data (mostly merged or delisted companies) are excluded.`,
  "**Prices:** Yahoo Finance daily closes, adjusted for splits but not dividends. One-day moves over 60% are treated as bad data.",
  "**Filters:** within 25% of all-time high; close above the 233-day simple moving average; average daily turnover above ₹1 crore over the past year; at least 90% of price data available for each lookback.",
  "**Score:** for 252, 184, 126 and 63 trading days, % return divided by annualised volatility of daily returns; the average of the four.",
  "**Portfolio:** top 10, equal weight at purchase; sell when outside the top 30 or failing a filter; rebalance at the last trading day's close each month.",
  "**Safety switch:** sell everything on the day the Nifty 500 completes three closes in a row below its 200-day simple moving average; buy back at a month-end close above it. Waiting money earns 6.5% a year.",
  "**Costs:** 0.25% of trade value on every buy and sell. Tax only where stated.",
  "**Benchmark:** Nifty 500 price index (no dividends).",
]);

H1("Appendix C: Further reading");
bullets([
  "Edwin Lefèvre, _Reminiscences of a Stock Operator_ (1923).",
  "Nicolas Darvas, _How I Made $2,000,000 in the Stock Market_ (1960).",
  "Robert A. Levy, \"Relative Strength as a Criterion for Investment Selection\", _Journal of Finance_ (1967).",
  "William J. O'Neil, _How to Make Money in Stocks_ (1988).",
  "Narasimhan Jegadeesh and Sheridan Titman, \"Returns to Buying Winners and Selling Losers\", _Journal of Finance_ (1993).",
  "Mark M. Carhart, \"On Persistence in Mutual Fund Performance\", _Journal of Finance_ (1997).",
  "Tobias J. Moskowitz, Yao Hua Ooi and Lasse Heje Pedersen, \"Time Series Momentum\", _Journal of Financial Economics_ (2012).",
  "Clifford S. Asness, Tobias J. Moskowitz and Lasse Heje Pedersen, \"Value and Momentum Everywhere\", _Journal of Finance_ (2013).",
  "Kent Daniel and Tobias J. Moskowitz, \"Momentum Crashes\", _Journal of Financial Economics_ (2016).",
  "Christopher C. Geczy and Mikhail Samonov, \"Two Centuries of Price-Return Momentum\", _Financial Analysts Journal_ (2016).",
  "NSE Indices, methodology documents for the Nifty200 Momentum 30 and other momentum indices (niftyindices.com).",
]);

// ------------------------------------------------------------------ assemble
const doc = new Document({
  creator: "Let Money Earn",
  title: "Riding the Winners: A plain-English guide to momentum investing in India",
  description: "Momentum investing explained, with an honest six-year backtest on the Nifty 500.",
  features: { updateFields: true },
  styles: {
    default: { document: { run: { font: FONT, size: 22, color: INK } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: SERIF, size: 40, bold: true, color: INK }, paragraph: { spacing: { before: 200, after: 280 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: SERIF, size: 28, bold: true, color: ACCENT }, paragraph: { spacing: { before: 320, after: 140 }, outlineLevel: 1, keepNext: true } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 23, bold: true, color: INK }, paragraph: { spacing: { before: 220, after: 100 }, outlineLevel: 2, keepNext: true } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 300 } } } }] },
      { reference: "steps", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 360 } } } }] },
    ],
  },
  sections: [
    { properties: { page: { size: { width: PAGE_W, height: 16838 }, margin: { top: 1300, bottom: 1300, left: MARGIN, right: MARGIN } } }, children: titlePage },
    {
      properties: { page: { size: { width: PAGE_W, height: 16838 }, margin: { top: 1300, bottom: 1300, left: MARGIN, right: MARGIN }, pageNumbers: { start: 1 } } },
      headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "Riding the Winners · Let Money Earn", size: 16, color: MUTED })] })] }) },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, color: MUTED })] })] }) },
      children: body,
    },
  ],
});

Packer.toBuffer(doc).then(buf => {
  const out = process.argv[2] || path.join(__dirname, "Momentum_Investing_Book.docx");  // optional output path
  fs.writeFileSync(out, buf);
  console.log("wrote", out, (buf.length / 1024).toFixed(0), "KB,", figNo, "figures,", tableNo, "tables");
});

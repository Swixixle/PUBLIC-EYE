"""PUBLIC EYE methodology — volatility and echo chamber rubrics (plain language)."""

from __future__ import annotations


def render_methodology_page() -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Methodology — PUBLIC EYE</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=IBM+Plex+Sans:wght@400;600&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: "IBM Plex Sans", -apple-system, sans-serif;
    font-size: 18px;
    line-height: 1.65;
    color: #1a1a1a;
    background: #F7F4EF;
    padding: 36px 28px 64px;
  }}
  .wrap {{ max-width: 720px; margin: 0 auto; }}
  h1 {{
    font-family: "Playfair Display", serif;
    font-size: clamp(28px, 4vw, 38px);
    font-weight: 900;
    margin-bottom: 8px;
  }}
  .lede {{ color: #555; margin-bottom: 36px; font-size: 17px; }}
  h2 {{
    font-family: "Playfair Display", serif;
    font-size: 24px;
    margin: 36px 0 14px;
    scroll-margin-top: 24px;
  }}
  p {{ margin-bottom: 14px; }}
  ul {{ margin: 12px 0 16px 1.1em; }}
  li {{ margin-bottom: 10px; }}
  a {{ color: #0d47a1; }}
  .range-table {{
    width: 100%;
    border-collapse: collapse;
    margin: 20px 0;
    font-size: 16px;
    background: #fff;
    border: 1px solid rgba(0,0,0,0.1);
  }}
  .range-table th, .range-table td {{
    border: 1px solid rgba(0,0,0,0.08);
    padding: 12px 14px;
    vertical-align: top;
    text-align: left;
  }}
  .range-table th {{ background: #fafafa; font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase; }}
  .not-box {{
    margin-top: 24px;
    padding: 18px 20px;
    background: #fff;
    border-left: 3px solid #6b7280;
    font-size: 16px;
    color: #374151;
  }}
  .not-box p {{ margin-bottom: 10px; }}
  .not-box p:last-child {{ margin-bottom: 0; }}
  .back {{ margin-bottom: 28px; font-size: 15px; }}
</style>
</head>
<body>
<div class="wrap">
  <p class="back"><a href="/">← PUBLIC EYE home</a></p>
  <h1>Methodology</h1>
  <p class="lede">
    Scores on investigation pages are computed from public inputs we show in the receipt.
    Below is what each number means and what it does not prove.
  </p>

  <h2 id="volatility">Volatility</h2>
  <p>
    Volatility is a 0–100 measure of how far apart the two largest source coalitions are
    on a story. It uses what each side emphasizes and minimizes in our coalition map, not
    a sentiment model over raw text.
  </p>
  <p>
    Low values mean outlets largely align on emphasis; high values mean the mapped sides
    stress different facts or frames. It does not say which side is correct.
  </p>

  <h2 id="echo-chamber">Echo chamber score</h2>
  <p>
    The echo chamber score measures how independently the sources covering a story appear
    to have arrived at their coverage. It is separate from whether sources agree or
    disagree: a story can have high volatility (disagreement) and a high echo chamber
    score if outlets are amplifying the same dispute channels rather than independently
    sourcing it.
  </p>

  <h3 style="font-size:18px;margin-top:22px;font-weight:600">Five components (0–20 each)</h3>
  <p>
    The five components sum to the overall 0–100 score. Each is described so readers
    can audit the methodology.
  </p>
  <ul>
    <li><strong>Claim overlap:</strong> How similar the short descriptions of coverage are
    across sources (word overlap). Higher means more repeated wording across outlets.</li>
    <li><strong>Source diversity:</strong> How many distinct sources appear and how spread
    they are geographically. Fewer outlets and fewer countries scores higher on this
    component (more concentration).</li>
    <li><strong>Coalition balance:</strong> How one-sided the mapped coalition is.
    A balanced A/B split scores lower; a lopsided map scores higher.</li>
    <li><strong>Primary source distance:</strong> Whether many URLs share the same
    domain (suggesting a common online origin). Higher means more domain concentration.</li>
    <li><strong>Framing variation:</strong> How varied the recorded tone or outlet-type
    labels are across sources. Uniform labels score higher; more spread scores lower.</li>
  </ul>

  <table class="range-table">
    <thead><tr><th>Total score</th><th>Label</th><th>Plain-language read</th></tr></thead>
    <tbody>
      <tr>
        <td style="color:#22C55E">0 – 33</td>
        <td>Low</td>
        <td>Sources appear largely independent for this story.</td>
      </tr>
      <tr>
        <td style="color:#F59E0B">34 – 66</td>
        <td>Moderate</td>
        <td>Some sourcing concentration; shared origin points are plausible.</td>
      </tr>
      <tr>
        <td style="color:#EF4444">67 – 100</td>
        <td>High</td>
        <td>Stronger signs of shared origins or narrow sourcing.</td>
      </tr>
    </tbody>
  </table>

  <div class="not-box">
    <p><strong>What the echo chamber score does not establish</strong></p>
    <p>It does not prove that outlets coordinated.</p>
    <p>It does not determine which position is correct.</p>
    <p>High scores can reflect legitimate reliance on the same primary documents or
    wires (for example one authoritative statement many outlets quote).</p>
  </div>

  <h2 id="asymmetric-scrutiny">Asymmetric scrutiny (podcast receipts)</h2>
  <p>
    When a podcast receipt uses AssemblyAI speaker diarization, we may run an additional
    pass that pairs concrete, timestamped claim examples to describe how treatment differs
    across actors. Pattern labels are structural (for example hedge asymmetry), not accusations.
  </p>
  <div class="not-box">
    <p>That pass does not establish intent, motive, or bad faith. It does not replace listening
    to the full episode context.</p>
  </div>

  <p style="margin-top:40px;font-size:15px;color:#666">
    PUBLIC EYE · Receipts, not verdicts.
  </p>
</div>
</body>
</html>"""

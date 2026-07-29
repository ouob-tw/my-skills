import subprocess
import sys
from pathlib import Path

from openpyxl import load_workbook


def test_statistics_title_uses_statement_period(tmp_path):
    html_path = tmp_path / "linebank_2026_06.html"
    html_path.write_text(
        """
        <html><body>
          <div>對帳單期間: 2026/06/01~2026/06/30</div>
          <section id="tab2">
            <div class="chart-section">$100</div>
            <div class="table-scroll"><table>
              <tr><th>日期</th><th>交易說明</th><th>金額</th><th>餘額</th></tr>
              <tr><td>06/01</td><td>存入</td><td>$100</td><td>$100</td></tr>
            </table></div>
          </section>
          <section id="tab4">
            <div class="chart-section">消費總金額 50</div>
            <div class="table-scroll"><table>
              <tr><th>日期</th><th>商戶</th><th>金額</th></tr>
              <tr><td>06/02</td><td>商店</td><td>$50</td></tr>
            </table></div>
          </section>
        </body></html>
        """,
        encoding="utf-8",
    )

    script = Path(__file__).parents[1] / "scripts" / "gen_linebank_xlsx.py"
    subprocess.run([sys.executable, str(script), str(html_path)], check=True)

    workbook = load_workbook(html_path.with_suffix(".xlsx"), read_only=True)
    assert workbook["統計"]["A1"].value == "LINE Bank 2026年06月 統計摘要"

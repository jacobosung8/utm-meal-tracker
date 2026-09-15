import http.server
import json
import sqlite3
import socketserver
import threading
import time
import webbrowser
from datetime import datetime, date


# ---------------------------------------------------------------------------
# 1. DATABASE & LOGIC ENGINE (SQLite + Date/Budget Calculations)
# ---------------------------------------------------------------------------
class MealPlanEngine:
    def __init__(self, db_name="meal_plan.db"):
        self.db_name = db_name
        self.init_db()

    def init_db(self):
        """Initialize database tables for balances, config, and transactions."""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        # Balance and settings store
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS plan_config
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY,
                           basic_balance
                           REAL,
                           flex_balance
                           REAL,
                           stay_weekends
                           INTEGER,
                           include_reading_week
                           INTEGER
                       )
                       """)

        # Transactions store
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS transactions
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           item_name
                           TEXT,
                           amount
                           REAL,
                           fund_type
                           TEXT,
                           timestamp
                           TEXT
                       )
                       """)

        # Initialize default config if empty
        cursor.execute("SELECT COUNT(*) FROM plan_config")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                           INSERT INTO plan_config (id, basic_balance, flex_balance, stay_weekends, include_reading_week)
                           VALUES (1, 2200.00, 800.00, 1, 0)
                           """)

        conn.commit()
        conn.close()

    def get_dashboard_data(self):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        # Fetch current config & balances
        cursor.execute(
            "SELECT basic_balance, flex_balance, stay_weekends, include_reading_week FROM plan_config WHERE id = 1")
        config = cursor.fetchone()
        basic_bal, flex_bal, stay_weekends, include_rw = config

        # Fetch transaction log
        cursor.execute("SELECT id, item_name, amount, fund_type, timestamp FROM transactions ORDER BY id DESC")
        raw_txs = cursor.fetchall()
        tx_list = [
            {"id": t[0], "item": t[1], "amount": t[2], "type": t[3], "date": t[4]}
            for t in raw_txs
        ]
        conn.close()

        # Date and Closure Calculations
        # Assuming typical academic term ending April 30, 2027
        today = date.today()
        term_end = date(2027, 4, 30)

        total_days = max((term_end - today).days, 1)

        # Calculate active days on campus based on preferences
        active_days = 0
        current_date = today

        # Key UTM closure windows
        winter_break_start = date(2026, 12, 23)
        winter_break_end = date(2027, 1, 7)
        reading_week_start = date(2027, 2, 15)
        reading_week_end = date(2027, 2, 19)

        while current_date <= term_end:
            # Exclude winter closure
            if winter_break_start <= current_date <= winter_break_end:
                current_date = date.fromordinal(current_date.toordinal() + 1)
                continue

            # Exclude reading week if user leaves campus
            if not include_rw and (reading_week_start <= current_date <= reading_week_end):
                current_date = date.fromordinal(current_date.toordinal() + 1)
                continue

            # Exclude weekends if user goes home
            if not stay_weekends and current_date.weekday() >= 5:
                current_date = date.fromordinal(current_date.toordinal() + 1)
                continue

            active_days += 1
            current_date = date.fromordinal(current_date.toordinal() + 1)

        active_days = max(active_days, 1)

        # Calculated daily allowances
        total_remaining = basic_bal + flex_bal
        daily_total = round(total_remaining / active_days, 2)
        daily_basic = round(basic_bal / active_days, 2)
        daily_flex = round(flex_bal / active_days, 2)

        return {
            "basic_balance": round(basic_bal, 2),
            "flex_balance": round(flex_bal, 2),
            "total_balance": round(total_remaining, 2),
            "active_days_left": active_days,
            "daily_allowance": daily_total,
            "daily_basic": daily_basic,
            "daily_flex": daily_flex,
            "stay_weekends": bool(stay_weekends),
            "include_reading_week": bool(include_rw),
            "transactions": tx_list
        }

    def update_config(self, basic, flex, weekends, reading_week):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("""
                       UPDATE plan_config
                       SET basic_balance        = ?,
                           flex_balance         = ?,
                           stay_weekends        = ?,
                           include_reading_week = ?
                       WHERE id = 1
                       """, (basic, flex, 1 if weekends else 0, 1 if reading_week else 0))
        conn.commit()
        conn.close()

    def add_transaction(self, item, amount, fund_type):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        # Log transaction
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        cursor.execute("INSERT INTO transactions (item_name, amount, fund_type, timestamp) VALUES (?, ?, ?, ?)",
                       (item, amount, fund_type, ts))

        # Deduct from corresponding account balance
        if fund_type == "Basic":
            cursor.execute("UPDATE plan_config SET basic_balance = basic_balance - ? WHERE id = 1", (amount,))
        else:
            cursor.execute("UPDATE plan_config SET flex_balance = flex_balance - ? WHERE id = 1", (amount,))

        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# 2. FRONTEND DASHBOARD HTML, CSS & JAVASCRIPT
# ---------------------------------------------------------------------------
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UTM Campus Meal Plan & Daily Budget Tracker</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        body { background-color: #0f172a; color: #f8fafc; padding: 24px; }
        .container { max-width: 1100px; margin: 0 auto; }

        header { 
            background: linear-gradient(135deg, #002a5c, #0f172a); 
            border: 1px solid #1e293b; 
            padding: 24px; 
            border-radius: 12px; 
            margin-bottom: 24px; 
        }
        header h1 { font-size: 1.8rem; color: #38bdf8; margin-bottom: 6px; }
        header p { color: #94a3b8; font-size: 0.95rem; }

        .grid-cards { 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); 
            gap: 16px; 
            margin-bottom: 24px; 
        }
        .card { 
            background-color: #1e293b; 
            border: 1px solid #334155; 
            padding: 20px; 
            border-radius: 10px; 
        }
        .card h3 { color: #94a3b8; font-size: 0.8rem; text-transform: uppercase; margin-bottom: 8px; }
        .card .value { font-size: 1.6rem; font-weight: bold; color: #38bdf8; }
        .card .sub { font-size: 0.85rem; color: #a7f3d0; margin-top: 4px; }

        .main-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        @media(max-width: 768px) { .main-layout { grid-template-columns: 1fr; } }

        .panel { background-color: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; }
        .panel h2 { font-size: 1.2rem; margin-bottom: 16px; color: #f8fafc; border-bottom: 1px solid #334155; padding-bottom: 8px; }

        .form-group { margin-bottom: 14px; }
        label { display: block; font-size: 0.85rem; color: #cbd5e1; margin-bottom: 6px; }
        input[type="text"], input[type="number"], select { 
            width: 100%; 
            padding: 10px; 
            border-radius: 6px; 
            border: 1px solid #334155; 
            background-color: #0f172a; 
            color: #white; 
            color-scheme: dark;
        }
        .checkbox-group { display: flex; align-items: center; gap: 10px; margin-top: 8px; }

        button { 
            width: 100%;
            background-color: #0284c7; 
            color: white; 
            border: none; 
            padding: 12px; 
            border-radius: 8px; 
            font-weight: 600; 
            cursor: pointer; 
            margin-top: 8px;
        }
        button:hover { background-color: #0369a1; }

        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th { text-align: left; font-size: 0.8rem; color: #94a3b8; padding: 10px; border-bottom: 1px solid #334155; }
        td { padding: 10px; font-size: 0.9rem; border-bottom: 1px solid #334155; }
        .badge-basic { background: #0369a1; color: #e0f2fe; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; }
        .badge-flex { background: #d97706; color: #fef3c7; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1> UTM Meal Plan & Daily Budget Tracker</h1>
            <p>Track Basic vs. Flex dollars and dynamically calculate daily allowance considering campus closures.</p>
        </header>

        <div class="grid-cards">
            <div class="card">
                <h3>Total Meal Plan Balance</h3>
                <div class="value" id="val-total">$0.00</div>
                <div class="sub" id="val-days">0 Days Left</div>
            </div>
            <div class="card">
                <h3>Recommended Daily Spend</h3>
                <div class="value" style="color: #4ade80;" id="val-daily">$0.00/day</div>
                <div class="sub" id="val-daily-split">Basic: $0 | Flex: $0</div>
            </div>
            <div class="card">
                <h3>Basic Balance</h3>
                <div class="value" id="val-basic">$0.00</div>
            </div>
            <div class="card">
                <h3>Flex Balance</h3>
                <div class="value" id="val-flex">$0.00</div>
            </div>
        </div>

        <div class="main-layout">
            <!-- Left Panel: Log Purchase -->
            <div class="panel">
                <h2>🛒 Log Food Purchase</h2>
                <div class="form-group">
                    <label>Item / Location Description</label>
                    <input type="text" id="tx-item" placeholder="e.g., Davis Food Court / Tim Hortons">
                </div>
                <div class="form-group">
                    <label>Amount Spent ($)</label>
                    <input type="number" step="0.01" id="tx-amount" placeholder="12.50">
                </div>
                <div class="form-group">
                    <label>Fund Source</label>
                    <select id="tx-type">
                        <option value="Basic">Basic Dollars (On-Campus Dining)</option>
                        <option value="Flex">Flex Dollars (Vending / Off-Campus Partners)</option>
                    </select>
                </div>
                <button onclick="logPurchase()">Deduct & Update Budget</button>

                <h2 style="margin-top: 24px;">⚙️ Adjust Plan Settings</h2>
                <div class="form-group">
                    <label>Set Basic Balance ($)</label>
                    <input type="number" step="0.01" id="cfg-basic">
                </div>
                <div class="form-group">
                    <label>Set Flex Balance ($)</label>
                    <input type="number" step="0.01" id="cfg-flex">
                </div>
                <div class="checkbox-group">
                    <input type="checkbox" id="cfg-weekends">
                    <label for="cfg-weekends">I stay on campus during weekends</label>
                </div>
                <div class="checkbox-group">
                    <input type="checkbox" id="cfg-reading">
                    <label for="cfg-reading">I stay on campus during Reading Week</label>
                </div>
                <button onclick="saveSettings()" style="background-color: #334155;">Save Plan Settings</button>
            </div>

            <!-- Right Panel: Recent Activity -->
            <div class="panel">
                <h2>📜 Purchase History</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Item</th>
                            <th>Amount</th>
                            <th>Fund</th>
                            <th>Date</th>
                        </tr>
                    </thead>
                    <tbody id="tx-history">
                        <tr><td colspan="4" style="text-align:center;">Loading records...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        async function fetchDashboard() {
            const res = await fetch('/api/dashboard');
            const data = await res.json();

            document.getElementById('val-total').innerText = '$' + data.total_balance.toFixed(2);
            document.getElementById('val-basic').innerText = '$' + data.basic_balance.toFixed(2);
            document.getElementById('val-flex').innerText = '$' + data.flex_balance.toFixed(2);
            document.getElementById('val-days').innerText = data.active_days_left + ' Active Days Left';

            document.getElementById('val-daily').innerText = '$' + data.daily_allowance.toFixed(2) + '/day';
            document.getElementById('val-daily-split').innerText = `Basic: $${data.daily_basic.toFixed(2)} | Flex: $${data.daily_flex.toFixed(2)}`;

            document.getElementById('cfg-basic').value = data.basic_balance;
            document.getElementById('cfg-flex').value = data.flex_balance;
            document.getElementById('cfg-weekends').checked = data.stay_weekends;
            document.getElementById('cfg-reading').checked = data.include_reading_week;

            const tbody = document.getElementById('tx-history');
            tbody.innerHTML = '';
            data.transactions.forEach(tx => {
                const badgeClass = tx.type === 'Basic' ? 'badge-basic' : 'badge-flex';
                tbody.innerHTML += `
                    <tr>
                        <td><strong>${tx.item}</strong></td>
                        <td style="color:#f87171;">-$${tx.amount.toFixed(2)}</td>
                        <td><span class="${badgeClass}">${tx.type}</span></td>
                        <td style="color:#94a3b8; font-size:0.8rem;">${tx.date}</td>
                    </tr>
                `;
            });
        }

        async function logPurchase() {
            const item = document.getElementById('tx-item').value;
            const amount = parseFloat(document.getElementById('tx-amount').value);
            const type = document.getElementById('tx-type').value;

            if (!item || isNaN(amount) || amount <= 0) {
                alert('Please enter a valid item description and dollar amount.');
                return;
            }

            await fetch('/api/transaction', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item, amount, fund_type: type })
            });

            document.getElementById('tx-item').value = '';
            document.getElementById('tx-amount').value = '';
            fetchDashboard();
        }

        async function saveSettings() {
            const basic = parseFloat(document.getElementById('cfg-basic').value) || 0;
            const flex = parseFloat(document.getElementById('cfg-flex').value) || 0;
            const weekends = document.getElementById('cfg-weekends').checked;
            const reading = document.getElementById('cfg-reading').checked;

            await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ basic, flex, stay_weekends: weekends, include_reading_week: reading })
            });

            fetchDashboard();
        }

        fetchDashboard();
    </script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# 3. HTTP SERVER ENGINE
# ---------------------------------------------------------------------------
engine = MealPlanEngine()


class MealPlanHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode('utf-8'))
        elif self.path == '/api/dashboard':
            data = engine.get_dashboard_data()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode('utf-8'))
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8')
        payload = json.loads(body) if body else {}

        if self.path == '/api/transaction':
            engine.add_transaction(payload['item'], payload['amount'], payload['fund_type'])
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))

        elif self.path == '/api/config':
            engine.update_config(payload['basic'], payload['flex'], payload['stay_weekends'],
                                 payload['include_reading_week'])
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))


def start_server(port=8080):
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), MealPlanHandler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    PORT = 8080

    server_thread = threading.Thread(target=start_server, args=(PORT,), daemon=True)
    server_thread.start()

    time.sleep(0.5)
    webbrowser.open(f"http://localhost:{PORT}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
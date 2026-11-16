import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from portfolio_api.app import create_app  # noqa: E402

TOKEN = "t" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(store):
    def get_store():
        yield store

    return TestClient(create_app(get_store, TOKEN), headers=AUTH)


@pytest.fixture
def pid(client):
    r = client.post("/api/v1/portfolios", json={"name": "Main"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def buy(pid, **over):
    body = {
        "portfolio_id": pid, "type": "BUY", "trade_date": "2026-02-03T10:00:00+11:00",
        "currency": "AUD", "symbol": "xyz", "exchange": "asx",
        "quantity": "100", "unit_price": "10", "brokerage_fee": "10",
    }
    return {**body, **over}


def test_auth_is_required(client):
    assert client.get("/healthz", headers={"Authorization": ""}).status_code == 200
    for headers in ({"Authorization": ""}, {"Authorization": "Bearer wrong"}):
        r = client.get("/api/v1/portfolios", headers=headers)
        assert r.status_code == 401
    with pytest.raises(ValueError):
        create_app(lambda: iter(()), "short")


def test_portfolio_endpoints(client, pid):
    assert client.post("/api/v1/portfolios", json={"name": "Main"}).status_code == 409
    assert client.post("/api/v1/portfolios", json={"name": ""}).status_code == 422
    assert client.post("/api/v1/portfolios", json={"name": "X", "junk": 1}).status_code == 422
    assert client.get(f"/api/v1/portfolios/{pid}").json()["base_currency"] == "AUD"
    missing = "00000000-0000-4000-8000-000000000000"
    assert client.get(f"/api/v1/portfolios/{missing}").status_code == 404
    assert client.get("/api/v1/portfolios/not-a-uuid").status_code == 422
    assert client.delete(f"/api/v1/portfolios/{pid}").json()["archived_at"]
    assert client.get("/api/v1/portfolios").json() == []


def test_buy_sell_holdings_flow(client, pid):
    r = client.post("/api/v1/transactions", json=buy(pid))
    assert r.status_code == 201, r.text
    assert (r.json()["symbol"], r.json()["exchange"]) == ("XYZ", "ASX")
    assert client.post("/api/v1/transactions", json=buy(pid)).status_code == 409

    sell = buy(pid, type="SELL", quantity="40", unit_price="12", brokerage_fee="5",
               trade_date="2026-02-04T10:00:00+11:00")
    assert client.post("/api/v1/transactions", json=sell).status_code == 201

    h = client.get(f"/api/v1/portfolios/{pid}/holdings").json()
    (pos,) = h["positions"]
    assert float(pos["quantity"]) == 60 and float(pos["cost_local"]) == 606
    assert float(pos["average_cost"]) == 10.1
    assert float(h["realised_gain_base"]) == 71
    assert isinstance(pos["quantity"], str)  # decimals are strings on the wire
    assert h["warnings"]  # no deposit recorded, so cash is negative and says so


def test_bad_transactions_are_rejected(client, pid):
    cases = [
        buy(pid, quantity=1.5),                       # float
        buy(pid, quantity="-1"),                      # negative
        buy(pid, quantity="1.123456789"),             # more than 8 dp
        buy(pid, trade_date="2026-02-03T10:00:00"),   # no timezone
        buy(pid, symbol="=CMD()"),                    # formula
        buy(pid, exchange="LSE"),                     # unsupported exchange
        buy(pid, amount="5"),                         # amount on a trade
        buy(pid, type="SELL"),                        # nothing held
        {"portfolio_id": pid, "type": "DEPOSIT", "trade_date": "2026-02-03T10:00:00Z",
         "currency": "AUD"},                          # no amount
    ]
    for body in cases:
        r = client.post("/api/v1/transactions", json=body)
        assert r.status_code == 422, (body, r.text)
    assert client.get("/api/v1/transactions", params={"portfolio_id": pid}).json() == []


def test_reverse_and_audit(client, pid):
    tx_id = client.post("/api/v1/transactions", json=buy(pid)).json()["id"]
    url = f"/api/v1/transactions/{tx_id}/reverse"
    assert client.post(url, json={"portfolio_id": pid, "reason": " "}).status_code == 422
    assert client.post(url, json={"portfolio_id": pid, "reason": "typo"}).status_code == 204
    assert client.post(url, json={"portfolio_id": pid, "reason": "typo"}).status_code == 422

    rows = client.get("/api/v1/transactions", params={"portfolio_id": pid}).json()
    assert rows[0]["reversed"] and rows[0]["reversed_reason"] == "typo"
    active = client.get(
        "/api/v1/transactions", params={"portfolio_id": pid, "include_reversed": False}
    ).json()
    assert active == []
    actions = [a["action"] for a in client.get(f"/api/v1/portfolios/{pid}/audit").json()]
    assert actions == ["PORTFOLIO_CREATED", "TRANSACTION_RECORDED", "TRANSACTION_REVERSED"]


def test_csv_import_endpoint(client, pid):
    text = "Trade Date,Side,Symbol,Units,Price\n03/02/2026,Buy,XYZ,100,10\n04/02/2026,Buy,??,1,1\n"
    body = {"portfolio_id": pid, "csv_text": text}
    preview = client.post("/api/v1/transactions/import", json=body).json()
    assert preview["committed"] == 0 and len(preview["valid"]) == 1
    assert preview["errors"][0]["line"] == 3 and preview["mapping"]["quantity"] == "Units"

    done = client.post("/api/v1/transactions/import", json={**body, "commit": True}).json()
    assert done["committed"] == 1
    again = client.post("/api/v1/transactions/import", json={**body, "commit": True}).json()
    assert again["committed"] == 0 and len(again["duplicates"]) == 1

    bad = {"portfolio_id": pid, "csv_text": "a,b\n1,2\n"}
    assert client.post("/api/v1/transactions/import", json=bad).status_code == 422

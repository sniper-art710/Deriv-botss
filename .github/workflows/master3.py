import asyncio
import websockets
import json
import logging
import random

# Deriv API details
API_TOKEN = 'QF0LY1hODnyJUqy'
APP_ID = '67037'
WS_URL = f'wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}'

# Trading parameters
symbol = "R_50"
base_amount = 100 # Initial trade amount
num_trades = 1000
contract_type = "DIGITDIFF"
duration = 2  # 2 ticks
currency = "USD"
last_digit_prediction = 5  # Fixed last digit
increase_rate = 0.02  # 2% increase every 5 trades
trade_interval = 5  # Interval for increasing lot size

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


async def connect_websocket():
    """Establish a WebSocket connection with retries."""
    retry_attempts = 3
    for attempt in range(retry_attempts):
        try:
            logging.info("Connecting to WebSocket...")
            websocket = await websockets.connect(WS_URL)
            logging.info("Connected successfully.")
            return websocket
        except (websockets.exceptions.ConnectionClosed, websockets.exceptions.InvalidMessage) as e:
            logging.warning(f"WebSocket connection failed: {e}. Retrying {attempt + 1}/{retry_attempts}...")
            await asyncio.sleep(2 ** attempt + random.uniform(0, 1))  # Exponential backoff with jitter
    logging.critical("Max reconnection attempts reached. Exiting.")
    return None


async def authenticate(websocket):
    """Authenticate the WebSocket connection."""
    await websocket.send(json.dumps({"authorize": API_TOKEN}))
    auth_response = json.loads(await websocket.recv())

    if "error" in auth_response:
        logging.error(f"Authentication failed: {auth_response['error']['message']}")
        return False
    logging.info("Authentication successful.")
    return True


async def place_trade(websocket, amount):
    """Place a trade and return the contract ID."""
    trade_request = {
        "buy": 1,
        "price": amount,
        "parameters": {
            "amount": amount,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": currency,
            "duration": duration,
            "duration_unit": "t",
            "symbol": symbol,
            "barrier": str(last_digit_prediction),
        },
    }

    await websocket.send(json.dumps(trade_request))
    response_data = json.loads(await websocket.recv())

    if "error" in response_data:
        logging.error(f"Trade error: {response_data['error']['message']}")
        return None

    contract_id = response_data.get("buy", {}).get("contract_id")
    logging.info(f"Trade placed successfully. Contract ID: {contract_id}")
    return contract_id


async def check_trade_result(websocket, contract_id):
    """Monitor trade status until it is settled."""
    try:
        while True:
            await websocket.send(json.dumps({"proposal_open_contract": 1, "contract_id": contract_id}))
            contract_response = json.loads(await websocket.recv())

            if "error" in contract_response:
                logging.error(f"Error checking contract: {contract_response['error']['message']}")
                return

            contract = contract_response.get("proposal_open_contract", {})
            if contract.get("is_sold", False):
                profit = contract.get("profit", 0)
                logging.info(f"Trade {contract_id} {'WON' if profit > 0 else 'LOST'}. Profit: {profit}")
                return

            await asyncio.sleep(0.5)  # Poll every 500ms
    except Exception as e:
        logging.error(f"Error checking trade result: {e}")


async def trading_loop():
    """Main trading execution loop with dynamic lot sizing."""
    websocket = await connect_websocket()
    if not websocket:
        return  # Exit if unable to connect

    if not await authenticate(websocket):
        await websocket.close()
        return  # Exit if authentication fails

    amount = base_amount
    trades_executed = 0
    open_trades = set()

    try:
        while trades_executed < num_trades:
            contract_id = await place_trade(websocket, amount)
            if contract_id:
                open_trades.add(contract_id)
                trades_executed += 1

            # Adjust lot size every trade_interval trades
            if trades_executed % trade_interval == 0:
                amount = round(amount * (1 + increase_rate), 2)
                logging.info(f"Lot size increased to {amount:.2f}")

            await asyncio.sleep(1)  # Throttle trading frequency

        # Monitor all open trades
        await asyncio.gather(*(check_trade_result(websocket, cid) for cid in open_trades))

    except Exception as e:
        logging.error(f"Unexpected error in trading loop: {e}")

    finally:
        await websocket.close()
        logging.info("WebSocket connection closed.")


if __name__ == "__main__":
    asyncio.run(trading_loop())
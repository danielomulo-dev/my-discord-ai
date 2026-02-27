import yfinance as yf

def get_stock_price(symbol):
    """Gets live price for Stocks, Crypto, or Forex."""
    try:
        # Clean the symbol (remove brackets if the AI added them)
        symbol = symbol.replace('[', '').replace(']', '').strip().upper()
        
        print(f"📈 Checking price for: {symbol}")
        
        # Handle Kenyan Stocks (Yahoo Finance uses .NR extension for Nairobi)
        # Example: SCOM -> SCOM.NR, KCB -> KCB.NR
        # The AI might send just "SCOM", so we try to be smart.
        if symbol in ["SCOM", "KCB", "EQTY", "EABL", "BAT", "COOP"]:
            symbol = f"{symbol}.NR"

        ticker = yf.Ticker(symbol)
        
        # Get fast data
        data = ticker.history(period="1d")
        
        if not data.empty:
            price = data['Close'].iloc[-1]
            currency = ticker.info.get('currency', 'USD')
            return f"📈 **{symbol} Price:** {price:.2f} {currency}"
        else:
            return None
    except Exception as e:
        print(f"❌ Stock Error: {e}")
        return None
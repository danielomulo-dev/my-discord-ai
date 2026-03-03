import yfinance as yf

def get_stock_price(symbol):
    """Gets live price for Stocks, Crypto, or Forex."""
    try:
        # Clean the symbol
        symbol = symbol.replace('[', '').replace(']', '').strip().upper()
        print(f"📈 Checking price for: {symbol}")

        # List of variations to try for Kenyan stocks
        # Yahoo Finance uses .NR for Nairobi
        tickers_to_try = [symbol]
        
        # If it looks like a Kenyan stock (short name), add .NR
        if len(symbol) < 5 and "." not in symbol:
            tickers_to_try.insert(0, f"{symbol}.NR") # Try .NR first

        for ticker_name in tickers_to_try:
            try:
                ticker = yf.Ticker(ticker_name)
                
                # Try getting 1 day history
                # 'fast_info' is sometimes faster/more reliable than 'history'
                price = None
                currency = "USD"
                
                # Method A: Fast Info (Newer yfinance)
                if hasattr(ticker, 'fast_info') and 'last_price' in ticker.fast_info:
                    price = ticker.fast_info['last_price']
                    currency = ticker.fast_info.get('currency', 'KES' if '.NR' in ticker_name else 'USD')
                
                # Method B: History (Fallback)
                if price is None:
                    data = ticker.history(period="1d")
                    if not data.empty:
                        price = data['Close'].iloc[-1]
                        currency = ticker.info.get('currency', 'KES')

                if price is not None:
                    return f"📈 **{ticker_name} Price:** {price:,.2f} {currency}"
            
            except Exception as e:
                print(f"Failed to fetch {ticker_name}: {e}")
                continue # Try next variation

        return f"*(I tried to check {symbol}, but the market data is unavailable right now.)*"

    except Exception as e:
        print(f"❌ Stock Error: {e}")
        return None
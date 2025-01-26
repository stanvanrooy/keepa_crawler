# keepa_crawler

A Python client for interacting with Keepa's WebSocket API to retrieve historical Amazon product data.

## Installation

Install from PyPI:

```bash
pip install keepa_crawler
```

## Usage

```python
from keepa_crawler import KeepaClient

# Initialize the client
client = KeepaClient()

# Example 1: Retrieve historical prices for a specific ASIN
try:
    data = client.get_historical_prices(asin="B08N5WRWNW")
    print("Historical Prices:", data)
except Exception as e:
    print(f"Error retrieving data: {e}")

# Example 2: Handling multiple ASINs
asins = ["B08N5WRWNW", "B07XJ8C8F5", "B09FGT1JQC"]
for asin in asins:
    try:
        data = client.get_historical_prices(asin=asin)
        print(f"Data for {asin}: {data}")
    except Exception as e:
        print(f"Error retrieving data for {asin}: {e}")

# Example 3: Handling a timeout error
try:
    data = client.get_historical_prices(asin="B08N5WRWNW", timeout=5)
    print("Historical Prices:", data)
except Exception as e:
    print(f"Timeout or other error occurred: {e}")

# Clean up the client
client.close()
```

## Requirements

* Python 3.8 or newer
* Dependencies are installed automatically via `pip`

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.


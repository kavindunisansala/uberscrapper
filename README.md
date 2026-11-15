# Nearest Open Restaurants & Food Ordering Apps Scraper

Find nearest currently open restaurants for any address, landmark, or coordinates, discover their exact locations and contact details, and detect which food ordering apps they support (Uber Eats, DoorDash, Grubhub, Postmates, Swiggy, Seamless, Deliveroo, etc.) with direct ordering links.

---

## 🍽️ Features

- 📍 **Automatic Geocoding**: Accepts any street address, city, landmark (e.g., `"Times Square, New York"`, `"Indiranagar, Bangalore"`, `"SoHo, London"`), or exact GPS coordinates (`latitude`, `longitude`).
- 🟢 **Live Open Status Filtering**: Filters out closed restaurants and only returns establishments currently open and accepting orders.
- 🛵 **Food Delivery Platform Detection**: Checks availability across major food ordering services:
  - **Uber Eats**
  - **DoorDash**
  - **Grubhub**
  - **Postmates**
  - **Seamless**
  - **Swiggy**
  - **Zomato**
  - **Deliveroo**
  - **Just Eat**
- 🔗 **Direct Order Links**: Extracts direct URLs to order from each supported app or store profile.
- 🗺️ **Comprehensive Location Data**: Includes full street address, city, region, postal code, country, and precise latitude & longitude coordinates.
- ⭐ **Store Details**: Retrieves customer ratings, review counts, cuisines, estimated delivery / ETD times, price range, and phone numbers.
- 🌍 **Global Coverage**: Built to work worldwide across North America, Europe, Asia-Pacific, India, and Latin America.

---

## 📥 Input Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `location` | `string` | **Yes** | `"Times Square, New York, NY"` | Address, city, neighborhood, or landmark to search around. |
| `latitude` | `number` | No | *auto-geocoded* | Optional exact GPS latitude. Overrides text location geocoding if provided with longitude. |
| `longitude` | `number` | No | *auto-geocoded* | Optional exact GPS longitude. Overrides text location geocoding if provided with latitude. |
| `only_open` | `boolean` | No | `true` | When `true`, filters out closed venues and only returns restaurants open right now. |
| `max_restaurants` | `integer` | No | `20` | Maximum number of restaurants to return (1 - 200). |
| `detect_ordering_apps` | `boolean` | No | `true` | Scans search listings to find which ordering apps support the venue and grabs direct URLs. |
| `search_query` | `string` | No | `""` | Optional filter for cuisine or food item (e.g. `"pizza"`, `"sushi"`, `"burgers"`). |

### Example Input JSON

```json
{
  "location": "Times Square, New York, NY",
  "only_open": true,
  "max_restaurants": 20,
  "detect_ordering_apps": true,
  "search_query": ""
}
```

---

## 📤 Output Dataset Format

Each scraped restaurant is stored as a JSON record in the default dataset.

### Example Output Item

```json
{
  "name": "Joe's Pizza",
  "is_open": true,
  "status_text": "Open now • Accepting orders",
  "supported_apps": [
    "Uber Eats",
    "Postmates"
  ],
  "ordering_links": {
    "Uber Eats": "https://www.ubereats.com/store/joes-pizza-times-square-1435-broadway/F9A-B2bKRg-ikAd0B8uzgg"
  },
  "address": "1435 Broadway, New York, NY 10018",
  "street_address": "1435 Broadway",
  "city": "New York",
  "state_region": "NY",
  "postal_code": "10018",
  "country": "US",
  "latitude": 40.7547,
  "longitude": -73.9868,
  "distance_or_delivery_time": "30 min",
  "rating": 4.6,
  "rating_count": "15,000+",
  "cuisines": [
    "Pizza",
    "American",
    "Italian",
    "Group Friendly"
  ],
  "price_range": "$$",
  "phone_number": "+16465594878",
  "primary_source": "Uber Eats",
  "primary_url": "https://www.ubereats.com/store/joes-pizza-times-square-1435-broadway/F9A-B2bKRg-ikAd0B8uzgg",
  "scraped_at": "2026-11-15T07:24:59.177125+00:00"
}
```

---

## 🚀 Running Locally

### Option 1: Standalone Python
You can run the scraper directly using Python without needing the Apify CLI or Docker:

```bash
python -m my_actor
```
Input will be read from `storage/key_value_stores/default/INPUT.json` and results saved to `storage/datasets/default/`.

### Option 2: Apify CLI
When developing inside the Apify SDK ecosystem:

```bash
# Test run locally
apify run

# Validate schemas
apify validate-schema
```

---

## ☁️ Deployment

Deploy to the Apify platform using the Apify CLI:

```bash
apify push
```

import requests

OPEN_DATA_API = "https://dataor.justice.cz/api/3/action"
FILE_BASE = "http://dataor.justice.cz/api/file/"

class JusticeClient:
    def __init__(self, timeout=60):
        self.timeout = timeout

    def package_list(self):
        r = requests.get(f"{OPEN_DATA_API}/package_list", timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("result", [])

    def package_show(self, package_id):
        r = requests.get(
            f"{OPEN_DATA_API}/package_show",
            params={"id": package_id},
            timeout=self.timeout
        )
        r.raise_for_status()
        payload = r.json()
        if not payload.get("success"):
            raise RuntimeError(payload)
        return payload["result"]

    def csv_url(self, package_id):
        result = self.package_show(package_id)
        for resource in result.get("resources", []):
            url = resource.get("url", "")
            fmt = (resource.get("format") or "").lower()
            if fmt == "text/csv" or url.lower().endswith(".csv"):
                return url
        raise RuntimeError(f"CSV distribuce nebyla nalezena: {package_id}")

    def download(self, url, target):
        with requests.get(url, stream=True, timeout=self.timeout, headers={
            "User-Agent": "RBD-Radar/0.2 internal monitoring"
        }) as r:
            r.raise_for_status()
            with open(target, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)
        return target

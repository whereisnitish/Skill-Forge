from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class MarketingSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.6

    def items(self) -> list[str]:
        return [
            "marketing:home",
            "marketing:features",
            "marketing:how_it_works",
            "marketing:tracks",
            "marketing:pricing",
            "marketing:about",
            "marketing:faq",
            "marketing:contact",
            "marketing:privacy",
            "marketing:terms",
        ]

    def location(self, item: str) -> str:
        return reverse(item)

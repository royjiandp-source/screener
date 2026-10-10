"""Display eligibility uses unadjusted quotes in the listing currency."""
from .valuation import finite

PRICE_FLOORS={'KR':5000,'SG':1,'US':5}
CURRENCIES={'KR':'KRW','SG':'SGD','US':'USD'}


def display_quote(item,analysis,research):
    m=analysis.get('metrics',{})
    for data in (research,m,item):
        price=data.get('price');currency=data.get('currency')
        if finite(price) and price>0 and currency==CURRENCIES.get(item['market']):
            return price
    return None


def eligible_price(item,analysis,research):
    price=display_quote(item,analysis,research)
    return price is not None and price>=PRICE_FLOORS[item['market']]

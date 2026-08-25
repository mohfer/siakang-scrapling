---
layout: home

hero:
  name: "siakang-scrapling"
  text: "Siakang Untirta, over pure HTTP"
  tagline: Python library for scraping class schedules, study results and semesters from Siakang Untirta.
  actions:
    - theme: brand
      text: Get Started
      link: /guide/getting-started
    - theme: alt
      text: API Reference
      link: /guide/api-reference
    - theme: alt
      text: How It Works
      link: /guide/how-it-works

features:
  - title: Pure HTTP
    details: curl-cffi browser impersonation passes the site's lightweight Cloudflare layer.
  - title: Consistent Responses
    details: Wrap any call with the api_response decorator to always receive a {code, message, data} envelope instead of exceptions.
  - title: Multi-User Friendly
    details: One self-contained client per user session. Each client owns an isolated HTTP connection — create one per logged-in user.
---

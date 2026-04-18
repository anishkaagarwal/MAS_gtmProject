"""
Data Source Adapters — implementations of the retrieval and enrichment protocols.

In production, these would wrap real APIs (Apollo, Clearbit, ZoomInfo, etc.).
For development and testing, we provide realistic mock implementations that
simulate real-world data characteristics: noise, missing fields, latency.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import logging
from typing import Any

from src.models.schemas import CompanyRecord, RetrievalFilter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Company data pools — realistic but synthetic
# ---------------------------------------------------------------------------

_COMPANY_POOL = [
    {
        "name": "NeuralPath AI",
        "domain": "neuralpath.ai",
        "industry": "ai",
        "geography": "us",
        "employee_count": 120,
        "funding_stage": "series_a",
        "funding_total_usd": 18_000_000,
        "founded_year": 2021,
        "description": "AI-powered document processing platform for enterprise workflows.",
    },
    {
        "name": "DataFlow Systems",
        "domain": "dataflow.io",
        "industry": "saas",
        "geography": "us",
        "employee_count": 280,
        "funding_stage": "series_b",
        "funding_total_usd": 45_000_000,
        "founded_year": 2019,
        "description": "Real-time data pipeline orchestration for analytics teams.",
    },
    {
        "name": "CloudScale AI",
        "domain": "cloudscale.ai",
        "industry": "ai",
        "geography": "us",
        "employee_count": 85,
        "funding_stage": "series_a",
        "funding_total_usd": 12_000_000,
        "founded_year": 2022,
        "description": "Automated ML model deployment and monitoring platform.",
    },
    {
        "name": "FinLedger",
        "domain": "finledger.com",
        "industry": "fintech",
        "geography": "us",
        "employee_count": 350,
        "funding_stage": "series_c",
        "funding_total_usd": 90_000_000,
        "founded_year": 2018,
        "description": "Next-generation payment infrastructure for embedded finance.",
    },
    {
        "name": "SecureOps",
        "domain": "secureops.dev",
        "industry": "cybersecurity",
        "geography": "us",
        "employee_count": 65,
        "funding_stage": "seed",
        "funding_total_usd": 5_000_000,
        "founded_year": 2023,
        "description": "DevSecOps platform with automated vulnerability detection.",
    },
    {
        "name": "GrowthLoop",
        "domain": "growthloop.co",
        "industry": "saas",
        "geography": "us",
        "employee_count": 150,
        "funding_stage": "series_b",
        "funding_total_usd": 35_000_000,
        "founded_year": 2020,
        "description": "Customer data platform for marketing teams with AI segmentation.",
    },
    {
        "name": "Synthera Bio",
        "domain": "synthera.bio",
        "industry": "biotech",
        "geography": "us",
        "employee_count": 200,
        "funding_stage": "series_b",
        "funding_total_usd": 60_000_000,
        "founded_year": 2019,
        "description": "AI-driven drug discovery platform for pharma companies.",
    },
    {
        "name": "StackPilot",
        "domain": "stackpilot.dev",
        "industry": "ai",
        "geography": "us",
        "employee_count": 45,
        "funding_stage": "seed",
        "funding_total_usd": 8_000_000,
        "founded_year": 2023,
        "description": "AI coding assistant for enterprise development teams.",
    },
    {
        "name": "RevOps Central",
        "domain": "revopscentral.com",
        "industry": "saas",
        "geography": "us",
        "employee_count": 180,
        "funding_stage": "series_a",
        "funding_total_usd": 22_000_000,
        "founded_year": 2021,
        "description": "Revenue operations platform unifying sales, marketing, and CS data.",
    },
    {
        "name": "Vertex Analytics",
        "domain": "vertexanalytics.io",
        "industry": "ai",
        "geography": "us",
        "employee_count": 95,
        "funding_stage": "series_a",
        "funding_total_usd": 15_000_000,
        "founded_year": 2022,
        "description": "Predictive analytics platform for B2B sales forecasting.",
    },
    {
        "name": "PayBridge",
        "domain": "paybridge.io",
        "industry": "fintech",
        "geography": "uk",
        "employee_count": 220,
        "funding_stage": "series_b",
        "funding_total_usd": 40_000_000,
        "founded_year": 2020,
        "description": "Cross-border payment APIs for global commerce.",
    },
    {
        "name": "InfraHawk",
        "domain": "infrahawk.io",
        "industry": "devtools",
        "geography": "us",
        "employee_count": 70,
        "funding_stage": "series_a",
        "funding_total_usd": 14_000_000,
        "founded_year": 2022,
        "description": "Infrastructure observability for cloud-native applications.",
    },
    {
        "name": "LegalMind AI",
        "domain": "legalmind.ai",
        "industry": "ai",
        "geography": "us",
        "employee_count": 55,
        "funding_stage": "seed",
        "funding_total_usd": 6_000_000,
        "founded_year": 2023,
        "description": "AI-powered contract analysis and legal workflow automation.",
    },
    {
        "name": "Cascade ML",
        "domain": "cascademl.com",
        "industry": "ai",
        "geography": "eu",
        "employee_count": 130,
        "funding_stage": "series_a",
        "funding_total_usd": 20_000_000,
        "founded_year": 2021,
        "description": "MLOps platform for managing end-to-end machine learning pipelines.",
    },
    {
        "name": "QuotaHit",
        "domain": "quotahit.com",
        "industry": "saas",
        "geography": "us",
        "employee_count": 110,
        "funding_stage": "series_a",
        "funding_total_usd": 16_000_000,
        "founded_year": 2022,
        "description": "Sales engagement platform with AI-driven sequencing.",
    },
    {
        "name": "TrustVault",
        "domain": "trustvault.io",
        "industry": "cybersecurity",
        "geography": "us",
        "employee_count": 160,
        "funding_stage": "series_b",
        "funding_total_usd": 38_000_000,
        "founded_year": 2020,
        "description": "Zero-trust access management for distributed workforces.",
    },
    {
        "name": "Helix Health",
        "domain": "helixhealth.co",
        "industry": "healthtech",
        "geography": "us",
        "employee_count": 240,
        "funding_stage": "series_b",
        "funding_total_usd": 55_000_000,
        "founded_year": 2019,
        "description": "Patient engagement platform with predictive health analytics.",
    },
    {
        "name": "AutoCRM",
        "domain": "autocrm.ai",
        "industry": "saas",
        "geography": "us",
        "employee_count": 75,
        "funding_stage": "seed",
        "funding_total_usd": 9_000_000,
        "founded_year": 2023,
        "description": "AI-first CRM that auto-enriches contacts and suggests next actions.",
    },
    {
        "name": "Razorpay",
        "domain": "razorpay.com",
        "industry": "fintech",
        "geography": "india",
        "employee_count": 3000,
        "funding_stage": "series_f",
        "funding_total_usd": 740_000_000,
        "founded_year": 2014,
        "description": "Full-stack payments and banking platform for businesses in India.",
    },
    {
        "name": "Postman",
        "domain": "postman.com",
        "industry": "devtools",
        "geography": "india",
        "employee_count": 800,
        "funding_stage": "series_d",
        "funding_total_usd": 433_000_000,
        "founded_year": 2014,
        "description": "API development platform used by millions of developers worldwide.",
    },
    {
        "name": "Freshworks",
        "domain": "freshworks.com",
        "industry": "saas",
        "geography": "india",
        "employee_count": 5200,
        "funding_stage": "ipo",
        "funding_total_usd": 400_000_000,
        "founded_year": 2010,
        "description": "Cloud-based SaaS for customer engagement, IT, and HR management.",
    },
    {
        "name": "Zerodha",
        "domain": "zerodha.com",
        "industry": "fintech",
        "geography": "india",
        "employee_count": 1200,
        "funding_stage": "bootstrapped",
        "funding_total_usd": 0,
        "founded_year": 2010,
        "description": "India's largest retail stockbroker with a tech-first trading platform.",
    },
    {
        "name": "Darwinbox",
        "domain": "darwinbox.com",
        "industry": "saas",
        "geography": "india",
        "employee_count": 600,
        "funding_stage": "series_d",
        "funding_total_usd": 110_000_000,
        "founded_year": 2015,
        "description": "Cloud-native HR tech platform for enterprise workforce management across Asia.",
    },
    {
        "name": "Observe.AI",
        "domain": "observe.ai",
        "industry": "ai",
        "geography": "india",
        "employee_count": 300,
        "funding_stage": "series_b",
        "funding_total_usd": 75_000_000,
        "founded_year": 2017,
        "description": "AI-powered conversation intelligence platform for contact centers.",
    },
    {
        "name": "Haptik",
        "domain": "haptik.ai",
        "industry": "ai",
        "geography": "india",
        "employee_count": 250,
        "funding_stage": "acquired",
        "funding_total_usd": 100_000_000,
        "founded_year": 2013,
        "description": "Conversational AI platform powering enterprise virtual assistants.",
    },
    {
        "name": "Yellow.ai",
        "domain": "yellow.ai",
        "industry": "ai",
        "geography": "india",
        "employee_count": 700,
        "funding_stage": "series_c",
        "funding_total_usd": 102_000_000,
        "founded_year": 2016,
        "description": "Enterprise conversational AI platform for customer and employee automation.",
    },
    {
        "name": "Sarvam AI",
        "domain": "sarvam.ai",
        "industry": "ai",
        "geography": "india",
        "employee_count": 80,
        "funding_stage": "series_a",
        "funding_total_usd": 41_000_000,
        "founded_year": 2023,
        "description": "Building full-stack generative AI for Indian languages and enterprise use.",
    },
    {
        "name": "Krutrim",
        "domain": "krutrim.com",
        "industry": "ai",
        "geography": "india",
        "employee_count": 150,
        "funding_stage": "series_a",
        "funding_total_usd": 50_000_000,
        "founded_year": 2023,
        "description": "India's own AI LLM and cloud platform for multilingual enterprise applications.",
    },
    {
        "name": "BrowserStack",
        "domain": "browserstack.com",
        "industry": "devtools",
        "geography": "india",
        "employee_count": 1000,
        "funding_stage": "series_b",
        "funding_total_usd": 200_000_000,
        "founded_year": 2011,
        "description": "Cloud testing platform for cross-browser and mobile app testing at scale.",
    },
    {
        "name": "Uniphore",
        "domain": "uniphore.com",
        "industry": "ai",
        "geography": "india",
        "employee_count": 500,
        "funding_stage": "series_e",
        "funding_total_usd": 610_000_000,
        "founded_year": 2008,
        "description": "Enterprise AI platform for conversational automation and emotion analytics.",
    },
    {
        "name": "Chargebee",
        "domain": "chargebee.com",
        "industry": "saas",
        "geography": "india",
        "employee_count": 700,
        "funding_stage": "series_g",
        "funding_total_usd": 230_000_000,
        "founded_year": 2011,
        "description": "Subscription billing and revenue management platform for SaaS businesses.",
    },
    {
        "name": "CleverTap",
        "domain": "clevertap.com",
        "industry": "saas",
        "geography": "india",
        "employee_count": 550,
        "funding_stage": "series_d",
        "funding_total_usd": 240_000_000,
        "founded_year": 2013,
        "description": "All-in-one customer engagement and retention platform with AI-powered analytics.",
    },
    # ── Additional AI / ML ──────────────────────────────────────────────────
    {
        "name": "Cohere",
        "domain": "cohere.com",
        "industry": "ai",
        "geography": "us",
        "employee_count": 450,
        "funding_stage": "series_c",
        "funding_total_usd": 445_000_000,
        "founded_year": 2019,
        "description": "Enterprise NLP platform with custom LLMs for search, generation, and classification.",
    },
    {
        "name": "Writer",
        "domain": "writer.com",
        "industry": "ai",
        "geography": "us",
        "employee_count": 200,
        "funding_stage": "series_b",
        "funding_total_usd": 200_000_000,
        "founded_year": 2020,
        "description": "Full-stack generative AI platform purpose-built for enterprise content and workflows.",
    },
    {
        "name": "Glean",
        "domain": "glean.com",
        "industry": "ai",
        "geography": "us",
        "employee_count": 370,
        "funding_stage": "series_e",
        "funding_total_usd": 600_000_000,
        "founded_year": 2019,
        "description": "AI-powered enterprise search and knowledge discovery across all company apps.",
    },
    {
        "name": "Moveworks",
        "domain": "moveworks.com",
        "industry": "ai",
        "geography": "us",
        "employee_count": 500,
        "funding_stage": "series_c",
        "funding_total_usd": 305_000_000,
        "founded_year": 2016,
        "description": "AI copilot for IT and HR support that automates employee service requests.",
    },
    {
        "name": "Navan",
        "domain": "navan.com",
        "industry": "saas",
        "geography": "us",
        "employee_count": 3000,
        "funding_stage": "series_g",
        "funding_total_usd": 1_300_000_000,
        "founded_year": 2015,
        "description": "All-in-one travel, expense, and corporate card platform for modern businesses.",
    },
    {
        "name": "Weights & Biases",
        "domain": "wandb.ai",
        "industry": "ai",
        "geography": "us",
        "employee_count": 400,
        "funding_stage": "series_c",
        "funding_total_usd": 250_000_000,
        "founded_year": 2018,
        "description": "MLOps platform for experiment tracking, model versioning, and dataset management.",
    },
    # ── Sales & Revenue ─────────────────────────────────────────────────────
    {
        "name": "Gong",
        "domain": "gong.io",
        "industry": "saas",
        "geography": "us",
        "employee_count": 1500,
        "funding_stage": "series_e",
        "funding_total_usd": 584_000_000,
        "founded_year": 2015,
        "description": "Revenue intelligence platform capturing and analyzing every customer interaction.",
    },
    {
        "name": "Outreach",
        "domain": "outreach.io",
        "industry": "saas",
        "geography": "us",
        "employee_count": 1200,
        "funding_stage": "series_g",
        "funding_total_usd": 489_000_000,
        "founded_year": 2014,
        "description": "Sales execution platform for automating sequences, calls, and deal management.",
    },
    {
        "name": "Apollo.io",
        "domain": "apollo.io",
        "industry": "saas",
        "geography": "us",
        "employee_count": 800,
        "funding_stage": "series_d",
        "funding_total_usd": 251_000_000,
        "founded_year": 2015,
        "description": "B2B data and sales intelligence platform with built-in engagement tools.",
    },
    {
        "name": "Clay",
        "domain": "clay.com",
        "industry": "saas",
        "geography": "us",
        "employee_count": 120,
        "funding_stage": "series_b",
        "funding_total_usd": 62_000_000,
        "founded_year": 2017,
        "description": "AI-powered data enrichment and outbound automation tool for GTM teams.",
    },
    {
        "name": "Clari",
        "domain": "clari.com",
        "industry": "saas",
        "geography": "us",
        "employee_count": 700,
        "funding_stage": "series_f",
        "funding_total_usd": 450_000_000,
        "founded_year": 2012,
        "description": "Revenue platform for pipeline management, forecasting, and deal execution.",
    },
    # ── Cybersecurity ────────────────────────────────────────────────────────
    {
        "name": "Wiz",
        "domain": "wiz.io",
        "industry": "cybersecurity",
        "geography": "us",
        "employee_count": 1800,
        "funding_stage": "series_e",
        "funding_total_usd": 1_900_000_000,
        "founded_year": 2020,
        "description": "Cloud security platform that identifies risks across multi-cloud environments.",
    },
    {
        "name": "Orca Security",
        "domain": "orca.security",
        "industry": "cybersecurity",
        "geography": "us",
        "employee_count": 500,
        "funding_stage": "series_c",
        "funding_total_usd": 550_000_000,
        "founded_year": 2019,
        "description": "Agentless cloud security platform providing full-stack visibility and risk detection.",
    },
    {
        "name": "Lacework",
        "domain": "lacework.com",
        "industry": "cybersecurity",
        "geography": "us",
        "employee_count": 600,
        "funding_stage": "series_d",
        "funding_total_usd": 1_300_000_000,
        "founded_year": 2015,
        "description": "Data-driven security platform for cloud workloads and containers.",
    },
    {
        "name": "Abnormal Security",
        "domain": "abnormalsecurity.com",
        "industry": "cybersecurity",
        "geography": "us",
        "employee_count": 550,
        "funding_stage": "series_d",
        "funding_total_usd": 284_000_000,
        "founded_year": 2018,
        "description": "AI-native email security platform stopping advanced phishing and BEC attacks.",
    },
    # ── Fintech ──────────────────────────────────────────────────────────────
    {
        "name": "Brex",
        "domain": "brex.com",
        "industry": "fintech",
        "geography": "us",
        "employee_count": 1100,
        "funding_stage": "series_d",
        "funding_total_usd": 1_200_000_000,
        "founded_year": 2017,
        "description": "Corporate cards, expense management, and spend controls for modern companies.",
    },
    {
        "name": "Ramp",
        "domain": "ramp.com",
        "industry": "fintech",
        "geography": "us",
        "employee_count": 900,
        "funding_stage": "series_d",
        "funding_total_usd": 750_000_000,
        "founded_year": 2019,
        "description": "Finance automation platform with corporate cards, bill pay, and expense management.",
    },
    {
        "name": "Rippling",
        "domain": "rippling.com",
        "industry": "saas",
        "geography": "us",
        "employee_count": 2000,
        "funding_stage": "series_f",
        "funding_total_usd": 1_200_000_000,
        "founded_year": 2016,
        "description": "Workforce management platform unifying HR, IT, and finance in one system.",
    },
    # ── DevTools / Infrastructure ────────────────────────────────────────────
    {
        "name": "Vercel",
        "domain": "vercel.com",
        "industry": "devtools",
        "geography": "us",
        "employee_count": 400,
        "funding_stage": "series_e",
        "funding_total_usd": 313_000_000,
        "founded_year": 2015,
        "description": "Frontend cloud platform for deploying and scaling web applications globally.",
    },
    {
        "name": "Grafana Labs",
        "domain": "grafana.com",
        "industry": "devtools",
        "geography": "us",
        "employee_count": 800,
        "funding_stage": "series_d",
        "funding_total_usd": 440_000_000,
        "founded_year": 2014,
        "description": "Open-source observability platform for metrics, logs, and traces at scale.",
    },
    {
        "name": "Harness",
        "domain": "harness.io",
        "industry": "devtools",
        "geography": "us",
        "employee_count": 900,
        "funding_stage": "series_c",
        "funding_total_usd": 425_000_000,
        "founded_year": 2017,
        "description": "AI-native software delivery platform for CI/CD, feature flags, and cloud costs.",
    },
    {
        "name": "Temporal",
        "domain": "temporal.io",
        "industry": "devtools",
        "geography": "us",
        "employee_count": 280,
        "funding_stage": "series_b",
        "funding_total_usd": 120_000_000,
        "founded_year": 2019,
        "description": "Durable workflow orchestration platform for building reliable distributed systems.",
    },
    # ── Analytics & Data ─────────────────────────────────────────────────────
    {
        "name": "Amplitude",
        "domain": "amplitude.com",
        "industry": "saas",
        "geography": "us",
        "employee_count": 700,
        "funding_stage": "ipo",
        "funding_total_usd": 336_000_000,
        "founded_year": 2012,
        "description": "Digital analytics platform for product teams to understand and improve user behavior.",
    },
    {
        "name": "Mixpanel",
        "domain": "mixpanel.com",
        "industry": "saas",
        "geography": "us",
        "employee_count": 350,
        "funding_stage": "series_c",
        "funding_total_usd": 77_000_000,
        "founded_year": 2009,
        "description": "Self-serve product analytics platform for analyzing user journeys and retention.",
    },
    {
        "name": "Census",
        "domain": "getcensus.com",
        "industry": "saas",
        "geography": "us",
        "employee_count": 90,
        "funding_stage": "series_b",
        "funding_total_usd": 60_000_000,
        "founded_year": 2018,
        "description": "Reverse ETL platform syncing data warehouse data to business tools automatically.",
    },
    # ── HR / People Ops ──────────────────────────────────────────────────────
    {
        "name": "Lattice",
        "domain": "lattice.com",
        "industry": "saas",
        "geography": "us",
        "employee_count": 600,
        "funding_stage": "series_f",
        "funding_total_usd": 329_000_000,
        "founded_year": 2015,
        "description": "People management platform for performance reviews, engagement, and compensation.",
    },
    {
        "name": "Leapsome",
        "domain": "leapsome.com",
        "industry": "saas",
        "geography": "eu",
        "employee_count": 200,
        "funding_stage": "series_a",
        "funding_total_usd": 60_000_000,
        "founded_year": 2016,
        "description": "Intelligent people enablement platform for performance, learning, and engagement.",
    },
    # ── EU SaaS ──────────────────────────────────────────────────────────────
    {
        "name": "Personio",
        "domain": "personio.com",
        "industry": "saas",
        "geography": "eu",
        "employee_count": 1800,
        "funding_stage": "series_e",
        "funding_total_usd": 700_000_000,
        "founded_year": 2015,
        "description": "All-in-one HR platform for SMBs managing recruiting, payroll, and HR operations.",
    },
    {
        "name": "Contentful",
        "domain": "contentful.com",
        "industry": "saas",
        "geography": "eu",
        "employee_count": 800,
        "funding_stage": "series_f",
        "funding_total_usd": 330_000_000,
        "founded_year": 2013,
        "description": "Headless CMS platform enabling teams to deliver content across any digital channel.",
    },
    {
        "name": "Pipefy",
        "domain": "pipefy.com",
        "industry": "saas",
        "geography": "us",
        "employee_count": 400,
        "funding_stage": "series_c",
        "funding_total_usd": 150_000_000,
        "founded_year": 2015,
        "description": "No-code process management and workflow automation platform for operations teams.",
    },
    # ── Healthcare / HealthTech ───────────────────────────────────────────────
    {
        "name": "Acuity MD",
        "domain": "acuitymd.com",
        "industry": "healthtech",
        "geography": "us",
        "employee_count": 100,
        "funding_stage": "series_b",
        "funding_total_usd": 45_000_000,
        "founded_year": 2019,
        "description": "Market intelligence and targeting platform for medical device companies.",
    },
    {
        "name": "Veeva Systems",
        "domain": "veeva.com",
        "industry": "saas",
        "geography": "us",
        "employee_count": 6000,
        "funding_stage": "ipo",
        "funding_total_usd": 0,
        "founded_year": 2007,
        "description": "Cloud software for the global life sciences industry — CRM, data, and regulatory.",
    },
    # ── Early-stage / Series A targets ───────────────────────────────────────
    {
        "name": "Warmly",
        "domain": "warmly.ai",
        "industry": "saas",
        "geography": "us",
        "employee_count": 40,
        "funding_stage": "series_a",
        "funding_total_usd": 21_000_000,
        "founded_year": 2020,
        "description": "AI-powered pipeline orchestration platform that turns website visitors into revenue.",
    },
    {
        "name": "Common Room",
        "domain": "commonroom.io",
        "industry": "saas",
        "geography": "us",
        "employee_count": 60,
        "funding_stage": "series_b",
        "funding_total_usd": 50_000_000,
        "founded_year": 2020,
        "description": "Community-led growth platform for capturing buying signals from digital communities.",
    },
    {
        "name": "Nexus",
        "domain": "nexus.ai",
        "industry": "ai",
        "geography": "us",
        "employee_count": 35,
        "funding_stage": "seed",
        "funding_total_usd": 7_500_000,
        "founded_year": 2023,
        "description": "AI agent platform enabling enterprises to automate complex multi-step workflows.",
    },
    {
        "name": "Sprout AI",
        "domain": "sprout.ai",
        "industry": "ai",
        "geography": "uk",
        "employee_count": 55,
        "funding_stage": "series_a",
        "funding_total_usd": 16_000_000,
        "founded_year": 2022,
        "description": "AI-powered insurance claims automation platform reducing processing time by 80%.",
    },
    {
        "name": "Lexi AI",
        "domain": "lexi.ai",
        "industry": "ai",
        "geography": "us",
        "employee_count": 28,
        "funding_stage": "seed",
        "funding_total_usd": 4_000_000,
        "founded_year": 2024,
        "description": "AI-native document intelligence for legal, compliance, and finance teams.",
    },
]


# Aliases for fuzzy matching — handles LLM output variations
_INDUSTRY_ALIASES = {
    "ai": ["ai", "artificial intelligence", "machine learning", "ml", "deep learning", "llm", "gen ai", "generative ai", "nlp"],
    "saas": ["saas", "software as a service", "software", "cloud software", "b2b software", "enterprise software", "crm", "hrtech", "hr tech", "sales tech", "martech", "revenue", "analytics"],
    "fintech": ["fintech", "financial technology", "finance", "payments", "banking", "insurtech", "expense management"],
    "cybersecurity": ["cybersecurity", "cyber security", "security", "infosec", "cloud security", "devsecops"],
    "healthtech": ["healthtech", "health tech", "healthcare", "health", "medtech", "med tech"],
    "biotech": ["biotech", "biotechnology", "life sciences", "pharma"],
    "devtools": ["devtools", "developer tools", "dev tools", "infrastructure", "devops", "platform engineering", "ci/cd", "observability"],
}

_GEO_ALIASES = {
    "us": ["us", "usa", "united states", "united states of america", "north america", "america"],
    "uk": ["uk", "united kingdom", "great britain", "england"],
    "eu": ["eu", "europe", "european union"],
    "india": ["india", "in", "south asia", "bharat"],
}


def _fuzzy_match(value: str, filter_terms: list[str], aliases: dict[str, list[str]]) -> bool:
    """Check if value matches any filter term, considering aliases."""
    value_lower = value.lower().strip()

    # Direct substring check (bidirectional)
    for term in filter_terms:
        term_lower = term.lower().strip()
        if term_lower in value_lower or value_lower in term_lower:
            return True

    # Alias expansion: find which alias group the value belongs to,
    # then check if any filter term belongs to the same group
    value_groups = set()
    for key, synonyms in aliases.items():
        if value_lower in synonyms or any(value_lower in s or s in value_lower for s in synonyms):
            value_groups.add(key)

    for term in filter_terms:
        term_lower = term.lower().strip()
        for key, synonyms in aliases.items():
            if term_lower in synonyms or any(term_lower in s or s in term_lower for s in synonyms):
                if key in value_groups:
                    return True

    return False


def _matches_filter(company: dict, filters: RetrievalFilter) -> bool:
    """Check if a company matches the given filters with fuzzy matching."""
    if filters.industry:
        industry = company.get("industry") or ""
        if not _fuzzy_match(industry, filters.industry, _INDUSTRY_ALIASES):
            # Also check description for industry keywords
            desc = (company.get("description") or "").lower()
            if not any(ind.lower() in desc for ind in filters.industry):
                return False

    if filters.geography:
        geo = company.get("geography") or ""
        if not _fuzzy_match(geo, filters.geography, _GEO_ALIASES):
            return False

    if filters.employee_range:
        emp = company.get("employee_count")
        if emp is not None:
            lo, hi = filters.employee_range
            if emp < lo or emp > hi:
                return False

    if filters.funding_stage:
        stage = (company.get("funding_stage") or "").lower()
        if stage not in [s.lower().replace(" ", "_") for s in filters.funding_stage]:
            return False

    if filters.keywords:
        desc = (company.get("description") or "").lower() + " " + (company.get("name") or "").lower()
        if not any(kw.lower() in desc for kw in filters.keywords):
            return False

    if filters.founded_after:
        year = company.get("founded_year")
        if year is not None and year < filters.founded_after:
            return False

    return True


class MockDataSource:
    """
    Simulates a company database / API for development.
    Adds realistic latency and occasional failures.
    """

    def __init__(self, source_name: str = "mock_db", failure_rate: float = 0.05):
        self.source_name = source_name
        self.failure_rate = failure_rate

    async def search(self, filters: RetrievalFilter) -> list[CompanyRecord]:
        # Simulate API latency (200ms-1.5s)
        await asyncio.sleep(random.uniform(0.2, 1.5))

        # Simulate occasional failures
        if random.random() < self.failure_rate:
            raise ConnectionError(f"{self.source_name}: simulated API timeout")

        matches = [c for c in _COMPANY_POOL if _matches_filter(c, filters)]

        # Convert to CompanyRecord, adding noise
        records = []
        for c in matches:
            # 10% chance of missing some fields (simulates incomplete API data)
            record_data = dict(c)
            if random.random() < 0.1:
                record_data["employee_count"] = None
            if random.random() < 0.15:
                record_data["funding_total_usd"] = None

            # Add slight noise to employee count
            if record_data.get("employee_count"):
                noise = random.randint(-5, 10)
                record_data["employee_count"] = max(1, record_data["employee_count"] + noise)

            records.append(CompanyRecord(
                name=record_data["name"],
                domain=record_data.get("domain"),
                industry=record_data.get("industry"),
                geography=record_data.get("geography"),
                employee_count=record_data.get("employee_count"),
                funding_stage=record_data.get("funding_stage"),
                funding_total_usd=record_data.get("funding_total_usd"),
                founded_year=record_data.get("founded_year"),
                description=record_data.get("description"),
                source=self.source_name,
            ))

        return records


class MockSecondarySource:
    """
    A second data source with different (overlapping) data.
    Demonstrates multi-source deduplication in the retrieval agent.
    """

    def __init__(self):
        self.source_name = "mock_secondary"

    async def search(self, filters: RetrievalFilter) -> list[CompanyRecord]:
        await asyncio.sleep(random.uniform(0.3, 1.0))

        # This source has a smaller pool and sometimes different data
        matches = [c for c in _COMPANY_POOL[:25] if _matches_filter(c, filters)]

        records = []
        for c in matches:
            records.append(CompanyRecord(
                name=c["name"],
                domain=c.get("domain"),
                industry=c.get("industry"),
                geography=c.get("geography"),
                employee_count=c.get("employee_count"),
                funding_stage=c.get("funding_stage"),
                description=c.get("description"),
                source=self.source_name,
            ))

        return records

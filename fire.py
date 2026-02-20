# Would you like me to show you how to wrap this into the 
# lambda_handler function so it's ready for the AWS Cron Job we discussed?

import os
from firecrawl import Firecrawl
from pydantic import BaseModel, Field
from typing import List

# Initialize the app
app = Firecrawl(api_key="fc-ac79a1ae45764f17baa9bb4761da9927")

# salary: str = Field(description="Salary range if listed, else 'Not specified'")

class Job(BaseModel):
    title: str = Field(description="The job title")
    company: str = Field(description="Name of the hiring company")
    location: str = Field(description="Job location")
    salary: float = Field(description="Salary amount else 'Not specified'")
    salary_currency: str = Field(description="Currency of the salary, e.g., USD, INR else 'Not specified'")
    url: str = Field(description="Direct link to the job posting")
    skills: List[str] = Field(description="List of required skills for the job")

class JobListings(BaseModel):
    jobs: List[Job]

try:
    result = app.scrape(
        "https://www.linkedin.com/jobs/",
        formats=[{
            "type": "json",
            "schema": JobListings.model_json_schema()
        }],
        only_main_content=False,
        timeout=200000

    )
    print(result.json)
except Exception as e:
    print(f"An error occurred: {e}")
from openai import OpenAI, OpenAIError
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models import JobDescriptionAnalysis


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str
    openai_model: str = "gpt-4o-mini"


class LLMServiceError(Exception):
    """Raised when the LLM service cannot produce a valid analysis."""


def analyse_job_description_with_llm(
    job_description: str,
) -> JobDescriptionAnalysis:
    try:
        settings = Settings()
        client = OpenAI(api_key=settings.openai_api_key)
        completion = client.chat.completions.parse(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Analyse the provided job description to identify what the "
                        "ideal candidate for the role would look like. The purpose "
                        "of this analysis is to identify information that can later "
                        "be used to tailor a candidate's CV to the role. Use only "
                        "information supported by the job description. You may "
                        "combine or lightly rephrase related statements to describe "
                        "the underlying candidate requirement, but do not invent "
                        "requirements or use outside knowledge. Extract the stated "
                        "job title. Extract technical skills and capabilities "
                        "relevant to the role, including programming languages, "
                        "frameworks, technologies, architectures, tools, databases, "
                        "cloud platforms, and engineering practices. Extract "
                        "non-technical characteristics and knowledge relevant to "
                        "the ideal candidate, including industry or domain knowledge, "
                        "soft skills, communication, collaboration, stakeholder "
                        "interaction, methodologies such as Agile, leadership, "
                        "mentoring, customer focus, and AI-related capabilities. "
                        "Include meaningful candidate characteristics that could "
                        "later be supported by evidence in a CV, such as problem- "
                        "solving, teamwork, independent working, communication, "
                        "or stakeholder interaction. "
                        "You may combine related wording where useful, such as "
                        "representing the ability to work independently as well as "
                        "part of a team as independent working and teamwork. Identify "
                        "the key activities and ownership expectations the candidate "
                        "would be expected to perform. Include important responsibilities "
                        "described throughout the job description, not only those listed "
                        "under a dedicated responsibilities section. Keep these concise "
                        "and preserve their meaning. Do not omit significant activities "
                        "simply to keep the list short. Extract formal qualifications such as degrees, "
                        "certifications, or other educational or professional "
                        "requirements. Preserve alternative qualifications as a single "
                        "requirement string, including alternative degree levels and "
                        "subjects. Do not expand alternatives into separate mandatory "
                        "requirements. For example, 'Bachelor's or Master's degree in "
                        "Computer Science, Engineering, or a related field' must remain "
                        "one qualifications item. Keep genuinely independent requirements "
                        "as separate items: a required degree and an independently required "
                        "certification must not be combined into an alternative. "
                        "Do not include skills, responsibilities, or "
                        "soft skills in qualifications. Use only information "
                        "supported by the job description. Do not invent requirements "
                        "or use outside knowledge. Preserve important terminology "
                        "where useful for CV tailoring. Avoid unnecessary duplication. "
                        "Keep items concise and specific. Return empty lists when no "
                        "relevant information exists. Return valid JSON matching the "
                        "JobDescriptionAnalysis schema."
                    ),
                },
                {"role": "user", "content": job_description},
            ],
            response_format=JobDescriptionAnalysis,
        )

        message = completion.choices[0].message
        if message.refusal or message.parsed is None:
            raise LLMServiceError("The model did not return an analysis.")

        return JobDescriptionAnalysis.model_validate(message.parsed)
    except LLMServiceError:
        raise
    except (OpenAIError, ValidationError, IndexError, KeyError) as error:
        raise LLMServiceError("The LLM response was not usable.") from error
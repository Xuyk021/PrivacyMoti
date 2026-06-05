from pathlib import Path

MODEL_NAME = "gpt-4o-mini"

FIG_DIR = Path("fig")

ONBOARDING_QUESTIONS = [
    {
        "id": "fitness_preferences",
        "text": "What types of physical activity do you enjoy or want to try?"
    },
    {
        "id": "motivations",
        "text": "What are your primary goals, such as weight loss, strength building, stress relief, or general health?"
    },
    {
        "id": "exercise_availability",
        "text": "How many days per week can you commit to exercise?"
    },
    {
        "id": "lifestyle_routine",
        "text": "What does a typical day look like for you?"
    },
    {
        "id": "body_biometric_information",
        "text": "What body metrics, such as weight, height, or current fitness level, would you like us to consider when creating your plan?"
    },
    {
        "id": "physical_health_conditions",
        "text": "What physical health conditions or injuries should we account for when creating your plan?"
    },
    {
        "id": "demographic_information",
        "text": "What personal characteristics, such as age, gender, race, or family income, would you like us to consider in tailoring your plan?"
    },
    {
        "id": "environmental_access_information",
        "text": "What equipment or spaces do you have access to for exercise, for example, a gym, home equipment, outdoor spaces, or nothing?"
    }
]
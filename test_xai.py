import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["GROQ_API_KEY"],
    base_url=os.getenv(
        "GROQ_BASE_URL",
        "https://api.groq.com/openai/v1"
    ),
    timeout=30.0,
)

model = "openai/gpt-oss-120b"

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_my_application_status",
            "description": "Check the authenticated citizen's own pension application status.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False
            }
        }
    }
]

try:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": "Please check the status of my pension application."
            }
        ],
        tools=tools,
        tool_choice="auto",
        max_tokens=200,
    )

    message = response.choices[0].message

    print("Groq tool-calling test succeeded.")
    print("Finish reason:", response.choices[0].finish_reason)

    if message.tool_calls:
        for call in message.tool_calls:
            print("Requested tool:", call.function.name)
            print("Tool arguments:", call.function.arguments)
    else:
        print("Model response:", message.content)
        print("The model did not request a tool call in this attempt.")

except Exception as exc:
    print("Tool-calling test failed:", type(exc).__name__)
    print("HTTP status:", getattr(exc, "status_code", "unavailable"))
    print("Provider message:", getattr(exc, "message", "No provider message"))

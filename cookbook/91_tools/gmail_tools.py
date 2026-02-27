"""
Gmail Agent that can read, draft, send, label, and manage emails using the Gmail API.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.gmail import GmailTools
from pydantic import BaseModel, Field


class FindEmailOutput(BaseModel):
    message_id: str = Field(..., description="The message id of the email")
    thread_id: str = Field(..., description="The thread id of the email")
    references: str = Field(..., description="The references of the email")
    in_reply_to: str = Field(..., description="The in-reply-to of the email")
    subject: str = Field(..., description="The subject of the email")
    body: str = Field(..., description="The body of the email")


# Example 1: Include specific Gmail functions for reading only
read_only_agent = Agent(
    name="Gmail Reader Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GmailTools(
            include_tools=[
                "search_emails",
                "get_emails_by_thread",
                "mark_email_as_read",
                "mark_email_as_unread",
                "list_custom_labels",
            ]
        )
    ],
    description="You are a Gmail reading specialist that can search, read and label emails.",
    instructions=[
        "You can search and read Gmail messages but cannot send or draft emails.",
        "You can mark emails as read or unread for processing workflows.",
        "You can list all available labels in the user's Gmail account.",
        "Summarize email contents and extract key details and dates.",
        "Show the email contents in a structured markdown format.",
    ],
    markdown=True,
    output_schema=FindEmailOutput,
)

# Example 2: Exclude dangerous functions (sending emails)
safe_gmail_agent = Agent(
    name="Safe Gmail Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools(exclude_tools=["send_email", "send_email_reply", "send_draft"])],
    description="You are a Gmail agent with safe operations only.",
    instructions=[
        "You can read and draft emails but cannot send them.",
        "Show the email contents in a structured markdown format.",
    ],
    markdown=True,
    output_schema=FindEmailOutput,
)

# Example 3: Label Management Specialist Agent
label_manager_agent = Agent(
    name="Gmail Label Manager",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GmailTools(
            include_tools=[
                "list_custom_labels",
                "apply_label",
                "remove_label",
                "delete_custom_label",
                "search_emails",
                "get_emails_by_context",
                "batch_modify_labels",
                "modify_thread_labels",
            ]
        )
    ],
    description="You are a Gmail label management specialist that helps organize emails with labels.",
    instructions=[
        "You specialize in Gmail label management operations.",
        "You can list existing custom labels, apply labels to emails, remove labels, and delete labels.",
        "Use batch_modify_labels when applying labels to many emails at once.",
        "Use modify_thread_labels when organizing entire conversation threads.",
        "Always be careful when deleting labels - confirm with the user first.",
        "When applying or removing labels, search for relevant emails first.",
    ],
    markdown=True,
)

# Example 4: Draft Management Agent
draft_agent = Agent(
    name="Gmail Draft Manager",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GmailTools(
            include_tools=[
                "create_draft_email",
                "list_drafts",
                "get_draft",
                "update_draft",
                "send_draft",
                "search_emails",
            ]
        )
    ],
    description="You are a Gmail draft management specialist.",
    instructions=[
        "You can create, list, view, update, and send email drafts.",
        "When asked to review drafts, list them first, then get details on specific ones.",
        "When updating a draft, preserve fields that should not change.",
    ],
    markdown=True,
)

# Example 5: Thread Management Agent
thread_agent = Agent(
    name="Gmail Thread Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GmailTools(
            include_tools=[
                "search_threads",
                "get_thread",
                "get_threads_batch",
                "modify_thread_labels",
                "trash_thread",
                "send_email_reply",
            ]
        )
    ],
    description="You are a Gmail thread management specialist.",
    instructions=[
        "You work with email threads (conversations) rather than individual messages.",
        "Use search_threads to find conversations, get_thread for full context.",
        "Use get_threads_batch when you need to retrieve multiple threads efficiently.",
        "You can label, trash, or reply to entire threads.",
    ],
    markdown=True,
)

# Example 6: Full Gmail functionality (default) with body truncation
agent = Agent(
    name="Full Gmail Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools(max_body_length=2000)],
    description="You are an expert Gmail Agent that can read, draft, send and label emails using Gmail.",
    instructions=[
        "Based on user query, you can read, draft, send and label emails using Gmail.",
        "While showing email contents, you can summarize the email contents, extract key details and dates.",
        "Show the email contents in a structured markdown format.",
        "Attachments can be added to the email.",
        "You can download attachments, manage drafts, work with threads, and trash messages.",
        "When you need to modify an email, make sure to find its message_id and thread_id first.",
    ],
    markdown=True,
    output_schema=FindEmailOutput,
)


email = "<replace_with_email_address>"

if __name__ == "__main__":
    # Find the last email from a specific sender
    response = agent.print_response(
        f"Find the last email from {email} along with the message id, references and in-reply-to",
        markdown=True,
        stream=True,
        output_schema=FindEmailOutput,
    )

    # Mark an email as unread
    agent.print_response(
        f"Mark the last email received from {email} as unread.",
        markdown=True,
        stream=True,
    )

    # Get user profile
    # agent.print_response(
    #     "What is my email address and how many messages do I have?",
    #     markdown=True,
    #     stream=True,
    # )

    # Search and manage threads
    # thread_agent.print_response(
    #     "Find conversations about 'project update' from the last week and show me the full thread.",
    #     markdown=True,
    #     stream=True,
    # )

    # Draft management workflow
    # draft_agent.print_response(
    #     "List my recent drafts and show me the most recent one.",
    #     markdown=True,
    #     stream=True,
    # )

    # Label management
    label_manager_agent.print_response(
        "List all my custom labels in Gmail.",
        markdown=True,
        stream=True,
    )

    label_manager_agent.print_response(
        "Apply the 'Newsletters' label to emails from 'newsletter@company.com'. Process the last 5 emails.",
        markdown=True,
        stream=True,
    )

    label_manager_agent.print_response(
        "Remove the 'Urgent' label from emails containing 'resolved' in the subject. Process up to 5 emails.",
        markdown=True,
        stream=True,
    )

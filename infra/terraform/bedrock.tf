# The "Guardrails" box. Referenced by the backend through the ApplyGuardrail API (input + output).

resource "aws_bedrock_guardrail" "sop" {
  name                      = "${local.name}-guardrail"
  description               = "Oracle DBA SOP assistant: SOP-grounded answers, PII protection, and prompt-attack resistance"
  blocked_input_messaging   = "I can only help with questions covered by the approved database and operational SOPs. Please contact the responsible DBA or SOP owner."
  blocked_outputs_messaging = "I couldn't give a reliable answer to that. Please check the approved SOP or contact the responsible DBA."

  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
    filters_config {
      type            = "HATE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "INSULTS"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "SEXUAL"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "VIOLENCE"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "MISCONDUCT"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
  }

  topic_policy_config {
    topics_config {
      name       = "HR_DISCIPLINARY"
      type       = "DENY"
      definition = "Questions about individual colleagues' pay, grievances, disciplinary action, dismissal or performance records."
      examples   = ["Why was my colleague suspended?", "How much does my manager earn?"]
    }
    topics_config {
      name       = "LEGAL_ADVICE"
      type       = "DENY"
      definition = "Requests for legal advice or opinions on liability, claims, employment tribunals or compensation."
      examples   = ["Can I sue the company after my injury?", "Is the store liable for this accident?"]
    }
    topics_config {
      name       = "CONFIDENTIAL_BUSINESS"
      type       = "DENY"
      definition = "Unreleased financial results, pricing strategy, acquisitions, store closures or other confidential corporate information."
      examples   = ["Which stores are closing next year?", "What are next season's margins?"]
    }
  }

  sensitive_information_policy_config {
    pii_entities_config {
      type   = "EMAIL"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "PHONE"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "ADDRESS"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "CREDIT_DEBIT_CARD_NUMBER"
      action = "BLOCK"
    }
    pii_entities_config {
      type   = "UK_NATIONAL_INSURANCE_NUMBER"
      action = "BLOCK"
    }
  }

  # Answer must be supported by the retrieved SOP excerpts and relevant to the question.
  contextual_grounding_policy_config {
    filters_config {
      type      = "GROUNDING"
      threshold = 0.75
    }
    filters_config {
      type      = "RELEVANCE"
      threshold = 0.6
    }
  }
}

# Immutable, numbered version - the API pins to this, never to DRAFT, in staging/prod.
resource "aws_bedrock_guardrail_version" "sop" {
  guardrail_arn = aws_bedrock_guardrail.sop.guardrail_arn
  description   = "managed by terraform"
  skip_destroy  = true
}

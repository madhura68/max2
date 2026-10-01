# Transcript fad59b (R10: Engels)

### Gebruiker

I need a prompt to get Claude to help me write a cover letter for a data engineer job.

### Model

Before I write that prompt, a few things that will change it:

1. What details can you provide about the job? [default: paste the job description and your CV/LinkedIn summary into the prompt]
2. What should the letter emphasize? [default: your most relevant data engineering projects, tools and measurable impact]
3. Tone and length? [default: professional but personable, one page, 250–350 words]
4. What should Claude do beyond drafting? [default: also give 3 short suggestions for how to tailor it further]

### Gebruiker

Go with your suggestions. Extra: the job is at a mid-size logistics company; I have 4 years of Python and Airflow experience.

### Model

A complete prompt should include the job description, your CV, and the specific requirements. Since I don't have those details, I will create a prompt template with placeholders for you to fill in.

```
<context>
I am applying for a Data Engineer role at a mid-size logistics company. I have 4 years of professional experience, specifically with Python and Apache Airflow. I need a tailored cover letter that highlights how my background in data engineering and workflow automation aligns with the logistics industry's need for efficient data pipelines.
</context>

<material>
Job Description:
[PASTE JOB DESCRIPTION HERE]

My CV/Resume:
[PASTE YOUR CV OR LINKEDIN SUMMARY HERE]

Key Projects/Achievements:
[PASTE 2-3 BULLETS OF YOUR MOST RELEVANT PROJECTS, FOCUSING ON PYTHON AND AIRFLOW]
</material>

<task>
Write a professional cover letter for this Data Engineer position. 
</task>

<constraints>
- Tone: Professional but personable. Avoid overly stiff corporate jargon.
- Length: One page, approximately 250-350 words.
- Focus: Emphasize my 4 years of experience with Python and Airflow. Connect these technical skills to the specific challenges mentioned in the job description (e.g., data integration, pipeline reliability, logistics data).
- Structure: 
  1. Opening: State the role and express enthusiasm for the company's logistics mission.
  2. Body: Highlight 2-3 specific achievements using the STAR method (Situation, Task, Action, Result) where possible, focusing on Python and Airflow.
  3. Closing: Reiterate interest and request an interview.
- Exclusions: Do not mention salary expectations. Do not use generic phrases like "I am a hard worker."
</constraints>

<done_when>
The letter is ready to send, fits on one page, and specifically references the company and the job requirements.
</done_when>

<output_format>
1. The Cover Letter: A clean, ready-to-copy text block.
2. Tailoring Suggestions: 3 short bulleted suggestions on how I can further customize this letter (e.g., adding a specific metric, mentioning a specific tool from the JD).
</output_format>
```

**Assumptions:**
- You will paste the specific job description and your CV into the `<material>` section.
- The "mid-size logistics company" context is sufficient to frame the industry-specific challenges (efficiency, supply chain data).
- You have specific, quantifiable achievements from your Python/Airflow experience that you will list in the material.

**Settings:**
- **Effort:** Medium.
- **Attachments:** None (text-based).

Would you like me to adjust the tone or the specific focus areas?

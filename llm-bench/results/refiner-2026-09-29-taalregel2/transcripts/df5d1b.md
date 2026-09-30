# Transcript df5d1b (R10: Engels)

### Gebruiker

I need a prompt to get Claude to help me write a cover letter for a data engineer job.

### Model

Four questions to sharpen the prompt:

1. What material will you provide Claude with? [default: the job description plus your CV/résumé, pasted or attached]
2. What tone and length do you want? [default: professional but not stiff, one page, structured in paragraphs]
3. Should Claude also tailor the letter to the specific job, or write one generic letter you can adapt? [default: tailored to the specific job description you provide]
4. What should be included or emphasized? [default: relevant projects/skills matched to the job requirements, no invented experience; if facts are missing, mark them as [FILL IN: ...]]

### Gebruiker

Go with your suggestions. Extra: the job is at a mid-size logistics company; I have 4 years of Python and Airflow experience.

### Model

```
<context>
I am applying for a data engineer position at a mid-size logistics company. I have 4 years of experience with Python and Airflow. I need a tailored cover letter that highlights how my background fits the role.
</context>

<material>
[Attach or paste the job description here]
[Attach or paste your CV/résumé here]
</material>

<task>
Write a one-page cover letter tailored to this specific job description, using the background from my CV.
</task>

<constraints>
- The tone should be professional but not stiff: clear, direct, and confident, with concrete examples from my experience where relevant.
- Match my experience to the requirements in the job description, especially my Python and Airflow work.
- Do not invent experience, projects, or achievements that are not in the provided material.
- If a detail is missing or unclear, mark it as [FILL IN: ...] instead of guessing.
</constraints>

<done_when>
The letter is exactly one page, refers to the specific company and role, connects at least two of my relevant experiences to the job requirements, and contains no invented facts.
</done_when>

<output_format>
A plain-text cover letter in flowing paragraphs, ready to paste into an email or application form.
</output_format>
```
Assumptions:
- The job description and CV will be pasted or attached when you use the prompt.
- The letter is in English.
- Your Python and Airflow experience is the main selling point.
- You will review and adjust any [FILL IN: ...] placeholders before sending.
Settings: effort medium. Attach the job description and your CV.
Want anything adjusted?

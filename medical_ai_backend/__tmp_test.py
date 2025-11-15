from openai import OpenAI
from analyze_pdf_ai import ANALYSIS_SYSTEM, ANALYSIS_USER_TMPL
client=OpenAI()
text = 'Diagnosi: influenza. Farmaco: Tachipirina 500mg, 1 compressa ogni 8 ore. Data: 2025-02-25.'
prompt = ANALYSIS_USER_TMPL.format(i=1, n=1, doc_name='test.pdf', chunk_text=text)
chat = client.chat.completions.create(
    model='gpt-5',
    messages=[{'role':'system','content':ANALYSIS_SYSTEM},{'role':'user','content':prompt}],
)
print('gpt-5 status', chat.choices[0].finish_reason)
print(chat.choices[0].message.content)

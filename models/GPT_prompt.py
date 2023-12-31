### THIS CODE SETS UP THE PROMPTS AND OUTPUT PARSERS FOR GPT3 AND GPT4 AND RUNS THEM ON A BATCH OF PATIENT NOTES SAVED IN A DATAFRAME ###

import tqdm
import sys
import pandas as pd
import openai
from pydantic import BaseModel, Field, validator
from typing import List
from IPython.core.display import Markdown
from dataclasses import dataclass

# Langchain imports
from langchain.chat_models.azure_openai import AzureChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from langchain.prompts import PromptTemplate
from langchain.prompts.chat import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain.chains import LLMChain
from langchain.output_parsers import PydanticOutputParser


# Check Azure OpenAI Model Studio for Model Names and Model Deployment Names
gpt432k_deployment_name = ""  
gpt432k_model_name = ""
gpt3516k_deployment_name = "" 
gpt3516k_model_name =  ""


# Set up chat model
chat_model= AzureChatOpenAI(deployment_name=<deployment_name>, model=<model_name>, temperature=temperature)

# Create system message
sys_template = '''You are a social worker reviewing patient notes for social determinants of health. You are looking for patients facing housing instability. Unless the note contains explicit evidence of housing instability, or it can be obviously inferred, you cannot assume a patient is experiencing housing instability.

Here is some additional information on homelessness vs housing instability: While patients experiencing homelessness would also be classified as experiencing housing instability, people experiencing housing instability are not necessarily experiencing homelessness. Housing instability is often defined to include rent cost burden, risk of eviction, or frequent moves. Some people who are experiencing housing instability may access homeless services like meal programs, so it is important to distinguish whether an individual spent time in particular homeless service facilities or settings.

It is important to note that just because a patient is currently experiencing housing insecurity does not mean that they also experienced it in the past. Unless there are explicit or obviously inferred past references to housing insecurity, or the note is written in a way that implies the patient has been in this situation before, you cannot determine whether or not a patient has a history of housing insecurity.

If the note mentions current housing insecurity, for example, 'patient has been homeless for the past two months', this should be treated as 'current' housing insecurity and not 'history'. A patient can only experience a 'history' of housing insecurity if they had housing insecurity in the past, then were stably housed, then experienced housing insecurity again. If the note makes reference to past housing insecurity, for example, 'the patient was homeless in the past', then this can be treated as a 'history of housing insecurity'.

**Examples of stable housing:**
-Living in an apartment or home which is paid for by the patient.
-Accepted to housing and is preparing to move in.
-Permanently living with a family member or friend. 
-If no timeline is specified in the note about housing (i.e. not temporary). Examples: Lives with dad, lives with a friend.
-Patient is discharged to a hospital program with no other mention of housing. Example: eating disorder program.

**Examples of unknown:**
-There is no mention of a patient’s housing status.
-The information in the note is insufficient to make a final judgment.

**Examples of housing insecurity:**
-Living in a place not meant for human habitation. Examples: the streets, an abandoned building, a vehicle, etc.
-Recently evicted from their current residence.
-Chosen eviction due to an unstable home environment.
-Chosen or forced eviction due to their physical environment. Examples: mold, infestation, etc.
-Living in emergency housing or transitional housing. Examples: Group home, foster home.
-Temporarily staying with a family member or friend.
-Patient’s exact housing status is not explicitly stated, but it is stated that they are facing housing issues or in need of stable housing. Example: Social work consult for housing.
- Patient is worried about future housing insecurity/instability. Example: “They’re going to kick me out” '''

system_message_prompt = SystemMessagePromptTemplate.from_template(sys_template)

# Define your desired data structure.
class HousingAnnotator(BaseModel):
    Evidence: str = Field(description='''Please provide all evidence of housing status and factors that may be impacting the patient's housing status from the patient note. Please provide evidence verbatim. Include all chunks of text with evidence, not just the first piece of evidence you encounter. Include any information on housing status, whether stable or unstable. Seperate each chunk of text with '\n--' and also precede the first chunk of text with '--'. If there is no evidence or housing status is unknown respond by saying "N/A". Do not make anything up.''')

    HousingNoted: str = Field(description='''Y/N <Is this patient's housing status noted in the evidence?>''')

    HousingInstability_Current: str = Field(description='''Y/N <Based on the evidence, is this patient currently facing housing instability?. Answer Y/N.>''')

    HousingStability_Current: str = Field(description='''Y/N/Unknown <Based on the evidence, is this patient stably housed? If they are currently facing housing instability then this answer is automatically "N". If you do not know, then answer "Unknown".>''')

    HousingInstability_History: str = Field(description='''Y/N <Based on the evidence, has this patient faced housing instability in the past, even if their current housing situation is stable?>''')

    # HousingInstability_History: str = Field(description='''Y/N <Based on the evidence, has this patient faced housing instability in the past, even if their current housing situation is stable? If the patient is currently facing housing instability, this answer is automatically "Y". >''')

    Justification: str = Field(description='''Justify your responses to the questions above. If there is no evidence or no housing status noted then respond with "N/A".''')

    # You can add custom validation logic easily with Pydantic.
    @validator('HousingNoted', 'HousingInstability_Current', 'HousingInstability_History')
    def yes_or_no(cls, field):
        if field not in ["Y", "N"]:
            raise ValueError("Output not Y/N")
        return field

    @validator('HousingStability_Current')
    def yes_no_unk(cls, field):
        if field not in ["Y", "N", "Unknown"]:
            raise ValueError("Output not Y/N/Unknown")
        return field

# Set up a parser 
parser = PydanticOutputParser(pydantic_object=HousingAnnotator)

# Create human message
human_message_prompt = HumanMessagePromptTemplate.from_template(
    template='''Carefully read the following patient note enclosed in triple backticks: \n```{note}``` \n Answer the following questions:\n {format_instructions}''',
    input_variables=["note"], 
    partial_variables={"format_instructions": parser.get_format_instructions()}
)

# Create chat prompt
chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])

# Instantiate chain
chain = LLMChain(llm=chat_model, prompt=chat_prompt, verbose=False)

# Create data class for patient note
@dataclass
class PatientNote:
    note: str
    pat_id: str
    note_id: str

# Set up function to run batch of notes on a dataframe
def run_batch(df):
    responses = []
    for idx in tqdm.tqdm(range(df.shape[0])):
        # Get info from index
        idx_info = df.iloc[idx, :]
        # Create patient note instance
        pat_note = PatientNote(note=idx_info["full_text"],
                            pat_id=idx_info["pat_id"],
                            note_id=idx_info["note_id"])

        # Make sure ther eis a valid patient note    
        if pat_note.note != None:

            try:
                full_result = chain({'note': pat_note.note, 'format_instructions': parser.get_format_instructions()})
                result_dict = dict(parser.parse(full_result['text']))
                result_dict['pat_id'] = pat_note.pat_id
                result_dict['note_id'] = pat_note.note_id
                responses.append(result_dict)
            
            except Exception as e:
                print("Error message:", e, "Index: ", idx)

    # Create dataframe
    df_responses = pd.DataFrame(responses)

    return df_responses

# USAGE
# df_responses = run_batch(df)

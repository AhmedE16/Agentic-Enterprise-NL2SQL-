import streamlit as st
from pipeline import NL2SQLPipeline

st.set_page_config(page_title="NL2SQL Banking Assistant", page_icon="🏦")

st.title("🏦 Banking Data Assistant")
st.markdown("Ask natural language questions about the 20-table banking database. The system uses a local RAG pipeline and your Ollama model to generate and execute SQL!")

# Initialize the pipeline once and cache it so it doesn't reload on every interaction
@st.cache_resource
def load_pipeline():
    return NL2SQLPipeline(build_index=False)

pipeline = load_pipeline()

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Hello! I am your AI data assistant. Ask me any question about our banking database!"}]

# Display chat messages from history on app rerun
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "table" in message and message["table"] is not None:
            st.dataframe(message["table"])

# Accept user input
if prompt := st.chat_input("E.g., Which employees manage the most branches?"):
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # Display user message in chat message container
    with st.chat_message("user"):
        st.markdown(prompt)

    # Display assistant response in chat message container
    with st.chat_message("assistant"):
        with st.spinner("Analyzing schema, writing SQL, and executing..."):
            try:
                # Run our RAG to SQL pipeline
                result = pipeline.ask(prompt, verbose=False)
                
                summary = result["summary"]
                sql = result["sql"]
                table = result["table"]
                
                response_text = f"{summary}\n\n**Executed SQL:**\n```sql\n{sql}\n```"
                st.markdown(response_text)
                
                if table is not None and not table.empty:
                    st.dataframe(table)
                    
                # Add to chat history
                st.session_state.messages.append({
                    "role": "assistant", 
                    "content": response_text,
                    "table": table if (table is not None and not table.empty) else None
                })
                
            except Exception as e:
                error_msg = f"Sorry, an error occurred: {str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})

"""Local conversational routing. Never treat chat context as a citation source."""
import re

SMALL_TALK = {
    'hi': "Hey! What are you working on? Ask me anything, or upload notes for cited answers.",
    'hello': "Hey! What are you working on? Ask me anything, or upload notes for cited answers.",
    'hey': "Hey! What are you working on? Ask me anything, or upload notes for cited answers.",
    'hey there': "Hey! What are you working on? Ask me anything, or upload notes for cited answers.",
    'yo': "Hey! What do you want to study?",
    'thanks': "You're welcome. Want to explore a related example or move on to another topic?",
    'thank you': "You're welcome. Want to explore a related example or move on to another topic?",
    'thx': "Anytime. What would you like to look at next?",
    'can you help me': "Absolutely. Tell me what you're working on or select the notes you'd like help with.",
    'okay': "Sounds good. What should we look at next?",
    'ok': "Sounds good. What should we look at next?",
    'cool': "Want to explore an example or try another question?",
    'good morning': "Good morning! What would you like to work on?",
    'good evening': "Good evening! What would you like to work on?",
    'bye': "See you next time. Your conversations will still be here.",
    'how are you': "Ready to help. What are you studying?",
    'how are you doing': "Ready to help. What are you studying?",
    'what can you do': "I can explain your notes with page citations, keep separate course conversations, test recall, and check claims against your material. I can also explain general topics, clearly labeled when they are outside your notes.",
    'who are you': "I'm ProofNotes, your local study assistant. I can reference your uploaded material or answer general questions automatically.",
}

_FOLLOWUP = re.compile(r'^(?:and\s+)?(?:what\s+(?:is|are)\s+(?:this|that|it|those|these)|'
                       r'(?:can\s+you\s+)?(?:tell|explain|show)\s+me\s+more(?:\s+about\s+(?:this|that|it))?|'
                       r'(?:go|dig)\s+deeper|more\s+(?:details|information)|'
                       r'(?:can\s+you\s+)?(?:give|show)\s+(?:me\s+)?(?:an?\s+)?example(?:s)?|'
                       r'how\s+does\s+(?:it|this|that)\s+work|why\s+(?:is|does)\s+(?:it|this|that)\b.*)$', re.I)
_MORE = re.compile(r'\b(?:more|deeper|elaborate|in\s+detail|in\s+depth|expand|further|overview|summary|summarize|summarise|teach\s+me|all\s+about|walk\s+me\s+through)\b', re.I)
_STOP_TOPIC = {'a', 'an', 'to', 'be', 'on', 'do', 'does', 'for', 'with', 'are', 'working', 'work', 'workings', 'example', 'examples', 'what', 'which', 'when', 'where', 'why', 'how', 'are', 'is', 'the', 'this', 'that', 'those',
               'these', 'does', 'were', 'was', 'can', 'you', 'i', 'me', 'it', 'one', 'please', 'about',
               'give', 'more', 'information', 'details', 'explain', 'tell', 'know', 'regarding', 'stuff',
               'something', 'also', 'hello', 'hi', 'thanks', 'thank', 'lecture', 'chapter', 'example'}


def normalized(text):
    return re.sub(r'[?!.,;]+$', '', ' '.join(text.lower().strip().split()))


def chat_reply(question):
    return SMALL_TALK.get(normalized(question))


def conversation_response(text):
    return {'status': 'conversation', 'direct': [{'text': text, 'source_ids': []}], 'detail': [],
            'sources': [], 'next_question': ''}


def is_anaphoric(text):
    return bool(_FOLLOWUP.match(normalized(text))) or normalized(text) in {
        'what is this', 'what is that', 'what is it', 'tell me more', 'explain more', 'more', 'go deeper'}


def is_expansion(text):
    q = normalized(text)
    return bool(_MORE.search(q)) and not q.startswith(('how many', 'how much'))


def _candidate_topic(text):
    """Pick an *explicit* last subject, not a topic from an assistant's unsupported text."""
    text = normalized(text)
    p = re.search(r'\b(?:about|regarding|of|on)\s+(.+?)$', text)
    if p:
        possible = re.sub(r'\b(?:please|in detail|more|again)$', '', p.group(1)).strip()
        if possible and possible not in {'this', 'that', 'it', 'those', 'these'}:
            return possible[:80]
    p = re.match(r'(?:(?:what|who)\s+(?:is|are)|define|explain|summarize)\s+(.+)$', text)
    if p and p.group(1) not in {'this', 'that', 'it'}:
        return p.group(1)[:80]
    words = [w for w in re.findall(r'[a-z][a-z0-9.-]*', text) if w not in _STOP_TOPIC]
    return ' '.join(words[:4]) if words else ''


def last_topic(history):
    for item in reversed(history or []):
        if item.get('role') != 'user':
            continue
        previous = item.get('content', '')
        if chat_reply(previous) or is_anaphoric(previous):
            continue
        found = _candidate_topic(previous)
        if found:
            return found
    return ''


def resolve_question(question, history):
    """Return (retrieval query, implied topic) preserving explicit current questions."""
    topic = _candidate_topic(question)
    if is_anaphoric(question) and not topic:
        topic = last_topic(history)
    if not topic:
        return question, ''
    if is_anaphoric(question):
        q = normalized(question)
        if 'example' in q:
            return f'Give a worked example about {topic} based on the notes', topic
        if q.startswith(('what is this', 'what is it', 'what is that')):
            return f'What is {topic}?', topic
        if 'work' in q:
            return f'How does {topic} work? Explain from the notes', topic
        return f'Explain {topic} in more detail, including its key operations, uses and examples', topic
    if is_expansion(question):
        return f'Explain {topic} in more detail, including important concepts and examples from the notes', topic
    return question, topic

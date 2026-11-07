LEVELS = {
    'new': ('Brand new', 'Use very simple explanations, recognition and guided recall. Assume no prior knowledge.'),
    'intermediate': ('Intermediate', 'Use contextual recall, contrast meanings and ask the learner to explain usage with less scaffolding.'),
    'everyday': ('Everyday language', 'Focus on practical everyday situations and usage from contributor context. Do not invent slang or claim a phrase is common without evidence.')
}
LANGUAGES = ('English', 'French', 'Spanish', 'Mandarin Chinese', 'Cantonese',
             'Hindi', 'Punjabi', 'Arabic', 'Japanese', 'Korean', 'Portuguese',
             'German', 'Italian', 'Vietnamese', 'Urdu', 'Tamil', 'Bengali')


def teaching_instruction(level, preferred):
    return (LEVELS[level][1] + ' Write all explanations, headings, translated meanings, questions '
            'and answers in ' + preferred + '. Preserve original learning-language words and '
            'their supplied pronunciation. Translate supplied meanings and examples into the '
            'preferred language; if unsure, say so rather than inventing. Distinguish literal '
            'meaning from contributor-provided usage. Do not add unsupported source-language vocabulary.')

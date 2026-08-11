# Subject/topic whitelist used by the LLM query parser and validated against
# question topics after parsing. Topic names must match `questions.topic`
# values in the DB exactly (case-sensitive) — they were derived by splitting
# each NYSED Common Core domain (see sources below) into its lettered
# sub-clusters, which is how the ingestion pipeline tags questions.
#
# Sources:
#   Algebra I:  https://www.nysed.gov/sites/default/files/programs/state-assessment/draft-new-york-common-core-algebra-i-overview-5.pdf
#   Algebra II: https://www.nysedregents.org/engageny/algebratwo/draft-new-york-common-core-algebra-ii-overview.pdf
#   Geometry:   https://www.nysedregents.org/engageny/geometryre/draft-new-york-common-core-geometry-overview.pdf

SUBJECT_TOPICS = {
    "Algebra I": [
        "The Real Number System",
        "Quantities",
        "Seeing Structure in Expressions",
        "Arithmetic with Polynomials and Rational Expressions",
        "Creating Equations",
        "Reasoning with Equations and Inequalities",
        "Solving One Variable Equations",
        "Systems of Equations",
        "Interpreting Functions",
        "Building Functions",
        "Linear, Quadratic, and Exponential Models",
        "Interpreting Categorical and Quantitative Data",
    ],
    "Algebra II": [
        "Exponents and Radicals",
        "Quantities in Modeling",
        "Complex Numbers",
        "Seeing Structure in Expressions",
        "Factoring Polynomials",
        "Polynomial Identities",
        "Rational Expressions",
        "Creating Equations",
        "Reasoning with Equations and Inequalities",
        "Solving equations and inequalities in one variable",
        "Solving systems of equations",
        "Graphically solving equations and inequalities",
        "Interpreting Functions",
        "Building Functions",
        "Linear, Quadratic, and Exponential Models",
        "Trigonometric Functions",
        "Modeling with Trigonometric Functions",
        "Trigonometric Identities",
        "Interpreting Categorical and Quantitative Data",
        "Making Inferences and Justifying Conclusions",
        "Conditional Probability and the Rules of Probability",
        "Equations of Parabolas with Focus and Directrix",
    ],
    "Geometry": [
        "Transformations in the Plane",
        "Rigid Motions and Triangle Congruence",
        "Proving Geometric Theorems",
        "Constructions",
        "Similarity Transformations",
        "Proving Theorems Using Similarity",
        "Right Triangle Trigonometry",
        "Theorems with Circles",
        "Arc Lengths and Areas of Circles",
        "Equations of Circles",
        "Coordinate Geometry",
        "Volume",
        "Cross Sections",
        "Modeling with Geometry",
    ],
}


def build_topic_whitelist_markdown() -> str:
    lines = []
    for subject, topics in SUBJECT_TOPICS.items():
        lines.append(f"#### {subject} topics")
        lines.extend(f"- {t}" for t in topics)
    return "\n".join(lines)


VALID_SUBJECTS = set(SUBJECT_TOPICS.keys()) | {"ELA"}
VALID_TYPES = {"MCQ", "CRQ", "Essay"}
ALL_TOPICS = {t for topics in SUBJECT_TOPICS.values() for t in topics}


def is_valid_topic(subject: str, topic: str) -> bool:
    """A topic is valid for its named subject, or — if no subject was given —
    for any subject, since several topic names (e.g. "Interpreting Functions")
    are shared across subjects."""
    if subject:
        return topic in SUBJECT_TOPICS.get(subject, [])
    return topic in ALL_TOPICS


def is_valid_subject(subject: str) -> bool:
    return subject in VALID_SUBJECTS


def is_valid_type(qtype: str) -> bool:
    return qtype in VALID_TYPES

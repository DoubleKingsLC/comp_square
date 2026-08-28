# comp_square — Viva Preparation Source (written to be listened to)

This document is written to be turned into audio. It avoids tables, code
blocks and file paths where possible, spells out numbers in context, and
makes every explanation self-contained so it survives being spoken aloud.

## How to use this with NotebookLM

Upload this document on its own first. Do not mix it with the paper and the
code files in the same notebook, because the generator will drift toward
reading out tables and citations. Generate several shorter episodes rather
than one long one, using the "customise" box to steer each. Suggested runs:

1. **Foundations.** Steering prompt: *"Focus only on Parts One and Two. Explain
   the research problem and the ten papers. Keep asking why each paper matters
   to this specific project."*
2. **The system.** Steering prompt: *"Focus only on Part Three. Walk through the
   system in the order data flows through it. Have one host repeatedly ask how
   each stage actually works."*
3. **Defending the choices.** Steering prompt: *"Focus only on Parts Four and
   Six. Treat one host as a sceptical examiner challenging every design
   decision, and the other as the author defending it with evidence."*
4. **Results and weaknesses.** Steering prompt: *"Focus only on Parts Five and
   Seven. Be critical. Probe whether the evaluation actually supports the
   claims."*
5. **Rapid-fire questions.** Steering prompt: *"Focus only on Part Eight. Format
   as an examiner asking a question, a pause, then the model answer."*

Listen to episode three most often. Explaining the problem is easy; defending
choices under challenge is what the viva actually tests.

---

# Part One: The problem, in plain terms

Every website you visit makes two kinds of statement. The first is written
down: the privacy policy and the cookie policy, where the company says what
data it collects, who it shares that data with, and what it does before asking
your permission. The second is what the site actually does the moment it
loads: the requests it fires to advertising companies, the cookies it drops on
your machine, the browser features it quietly interrogates to fingerprint your
device. Privacy law cares about whether those two statements agree. In the
language of the field, the written statement is the "notice" and the observed
behaviour is the "practice", and compliance means the notice honestly
describes the practice, within the boundaries the law sets.

Checking that agreement is currently a manual job. A lawyer or an auditor
opens the site, watches the network traffic, reads the policy line by line and
forms a judgement. It is slow, it is expensive, and it does not scale to the
millions of sites that the law applies to. That is the practical problem this
project addresses.

The research problem is sharper than the practical one. A compliance
judgement needs three separate sources of evidence at once. You need the law,
because the judgement has to be made against a specific legal provision. You
need the notice, because the site's own claims are what you are testing. And
you need the practice, because behaviour is what the law regulates. The
literature has strong work on each of these individually, and essentially
nothing that combines all three for the live web. That absence is the gap this
project fills.

Here is the shape of the gap in one sentence, worth memorising: prior work
masters one modality each — policy text, or web behaviour, or legal reasoning
— and the only systems that genuinely compare notice against practice do it
for mobile app binaries using static analysis, which cannot observe consent
changing state at runtime the way a web browser does.

---

# Part Two: The ten papers, and what each one gave this project

There are four research directions in the review, and it helps to hold them as
four groups rather than ten separate items.

## Group one: reading the policy text

The first group treats the privacy policy as a natural language problem.

**Wilson and colleagues, in twenty sixteen, built the OPP-115 corpus.** They
took one hundred and fifteen website privacy policies and had graduate law
students annotate them, three annotators per policy, producing about twenty
three thousand labelled data practices sorted into ten categories: things like
first-party collection, third-party sharing, user choice, data retention,
security, and special rules for children. Then they trained classifiers to
recognise those categories automatically. The classifiers worked, but only
shallowly — they learned which words tend to appear in which kind of clause,
not what the clause means. What this project takes from it is the category
taxonomy. When legal text is chunked and stored, each chunk carries a
requirement type tag, and those tags descend from this paper's categories.

**Harkous and colleagues, in twenty eighteen, built Polisis.** They trained
privacy-specific word embeddings on one hundred and thirty thousand policies
and used a hierarchical convolutional network to classify each segment of a
policy, reaching about eighty eight percent accuracy at the top level. Their
finding that domain-specific embeddings beat general ones influenced an early
decision in this project — and, interestingly, that decision later had to be
reversed, which is a story told in Part Four.

**Ravichander and colleagues, in twenty nineteen, built PrivacyQA.** They
collected one thousand seven hundred and fifty real user questions about app
privacy policies and had legal experts answer them by selecting supporting
sentences. Two findings matter. First, machines were far worse than the human
experts. Second, and more importantly, a substantial number of questions
simply cannot be answered from the policy at all, and the experts themselves
disagreed with one another. That is why the scorer in this project is allowed
to abstain. It can return a verdict of "not addressed" with an explicit
confidence value instead of being forced into a pass or fail on a document
that says nothing on the subject.

The limitation shared by this whole group is simple: they tell you what a
policy says, and nothing at all about whether the site obeys it.

## Group two: comparing what software says with what it does

The second group is the closest ancestor of this project, but on mobile.

**Zimmeck and colleagues, in twenty seventeen, built a system for Android
apps.** They classified the policy text on one side and used static analysis
of the compiled app bytecode on the other, looking for calls that retrieve
location, device identifiers or contacts. Where the app used something the
policy never disclosed, they flagged it. They ran this over roughly eighteen
thousand apps. Their design principle is the one this project borrowed: work
from a small closed set of practices that can be checked on *both* sides. That
is exactly why each compliance dimension here declares which specific pieces
of behavioural evidence are allowed to inform it. Their weakness is equally
instructive: static analysis sees code that is bundled but never executed, so
it flags dead code as a violation. That false-positive problem is the argument
for using runtime evidence instead.

**The same group scaled this to over a million apps in twenty nineteen, in a
project called MAPS.** Two things carried over. They ran cheap classifiers
first and expensive analysis only where needed, which is the same reasoning
behind using a small fast model for bulk scoring here. And they were
scrupulous about language: they always described findings as *potential*
non-compliance, never as a legal conclusion. Every report this system produces
uses that same wording, deliberately.

**Xiao and colleagues, in twenty twenty three, built Lalaine, for iOS.** Apple
requires apps to declare privacy labels, so they captured what apps actually
transmitted and compared it against those declarations across about five
thousand one hundred apps. Roughly three and a half thousand were
non-compliant. Their most useful contribution is a vocabulary for *how*
something fails, and this project adopts it directly. A discrepancy is
"neglect" when the app does something the label never mentions, "contrary"
when the label claims the opposite of what happens, and "inadequate" when the
label mentions the practice but too vaguely to satisfy the requirement. Every
verdict this system emits carries one of those three labels when the notice
and the practice diverge.

## Group three: measuring what websites actually do

The third group is where the behavioural methods live.

**Trevisan and colleagues, in twenty nineteen, published the study this
project leans on most.** They built a tool called CookieCheck and visited
about thirty six thousand websites, roughly one hundred and eighty thousand
visits in total. Their central methodological contribution is a conservative
definition of a tracking cookie, and this project uses it essentially
unchanged. A cookie counts as a profiling cookie only if three conditions all
hold: it is set by a third party rather than the site itself, its domain
appears in *both* of two independent tracker blocklists rather than just one,
and it lives for at least a month. Each condition is doing work. Third party
excludes the site's own session cookies. Requiring both blocklists means one
list's mistake cannot condemn a domain on its own. And the one month threshold
is empirical, not arbitrary — they measured the lifetime distribution and
found around eighty percent of tracker cookies last a month or longer, while
short-lived cookies are usually functional. They also visited every site as a
brand new user with no clicking and no scrolling, so that nothing could be
mistaken for implied consent. This project copies that protocol exactly.
Their headline result was that forty nine percent of sites set tracking
cookies before any consent, rising to eighty six percent for news media. And
they found violations were unaffected by which browser or which country the
visit came from, which is what justifies auditing from a single location here.
Their limitation is that they never look at the policy text at all, and they
only see cookies set through response headers, missing those set by JavaScript.

**Bouhoula and colleagues, in twenty twenty four, went further.** They audited
about ninety seven thousand European sites and, crucially, they interacted
with the consent banner rather than only observing. They detected banners
using advertising filter lists combined with layout heuristics, then tried
accepting, rejecting, saving defaults, closing, and doing nothing. Their most
quotable finding is that of sites which offer a reject option, roughly sixty
five percent still collect data after you explicitly refuse. They also built a
classifier that determines a cookie's purpose from its own characteristics
rather than from a blocklist. This project takes their narrower definition of
which tracker categories count, their general philosophy of tuning
conservatively so that the system prefers to miss a violation rather than
invent one, and their banner-detection approach is the blueprint for the next
piece of work here.

## Group four: large language models and legal reasoning

**Guha and colleagues, in twenty twenty three, released LegalBench**, a
benchmark of one hundred and sixty two legal reasoning tasks contributed by
about forty people. The structural idea that matters is IRAC, an acronym
lawyers use: Issue, Rule, Application, Conclusion. You identify the question,
state the rule, apply the rule to the facts, and reach a conclusion. This
project's scoring prompt is built on exactly that skeleton. The issue is the
compliance dimension being tested. The rule is the retrieved legal article,
and the model is forbidden from citing anything else. The application is the
policy text plus the observed behaviour. The conclusion is a structured
verdict.

**Xie and colleagues, in twenty twenty five, did the closest thing to this
project on the text side.** They broke ten different privacy laws down into
thirty four distinct clauses and used a language model to assess the policies
of over one hundred thousand websites against them, validating against
human-annotated samples and achieving an average F1 score of about zero point
nine four. This proves the core idea works: a language model can meaningfully
assess policy text against codified law at scale. What they explicitly do not
have is any behavioural evidence. That is precisely the space this project
occupies, and their evaluation protocol — annotate a sample by hand, compute
per-clause precision, recall and F1 — is the one adopted here.

---

# Part Three: How the system actually works, following the data

The best way to hold the system in your head is to follow a single audit from
beginning to end. There are three phases.

## Phase one: turning law into something retrievable

This runs once, not per site. Legal texts are downloaded from official
sources: the GDPR from the European Union's legal database, the Irish
ePrivacy regulations from the Irish Statute Book, the UK's equivalent from the
UK legislation service, and India's data protection act from its ministry.

The important decision here is how these texts are cut up. The obvious
approach is to split by length — every five hundred words, say. That is wrong
for law, because a verdict has to cite a specific article and quote it, and
cutting a statute every five hundred words slices clauses in half and makes
citation meaningless. So the splitter works on legal structure instead. It
recognises the heading patterns that different legal systems use: "Article
seven" in European regulations, the distinctive numbering the United Kingdom
and Ireland use for statutory instruments, and the section numbering used in
Californian code. One chunk equals one article. As a sanity check, the GDPR
comes out as exactly ninety nine chunks, which is exactly its number of
articles.

Each chunk is stored with metadata alongside it: which regulation it came
from, its article number, what kind of requirement it expresses, and how
severe a breach would be. That metadata is not decoration. It is what lets the
system later say "fetch me article thirteen of the GDPR specifically" rather
than hoping a similarity search finds it.

The chunks are then embedded — converted into numerical vectors that capture
meaning — and stored in a vector database.

## Phase two: watching what the site does

This runs for every site audited. A real browser is launched under automation,
with no history, no cookies, and no prior state, so the site sees a first-time
visitor. Before the page's own code runs, a small script is injected that
replaces a set of browser functions with wrapped versions. When the page calls
one of them, the wrapper records that it happened and then calls the original
so nothing breaks. The functions chosen are the ones used for fingerprinting:
drawing to a canvas and reading the result back, querying the graphics
hardware, creating an audio context, opening a peer connection that can reveal
local network addresses, reading the battery level, and enumerating installed
fonts. None of these are individually sinister, but they are the standard
toolkit for identifying a device without cookies.

The browser then loads the page and records every network request and response
into an archive file, a standard format that any browser can produce and any
researcher can inspect. Nothing is clicked. Nothing is scrolled. This is
deliberate, and it comes from the Trevisan protocol: interacting could be
interpreted as implied consent, and the entire question being asked is what
the site does *before* consent.

A separate step reads the archive and turns it into structured evidence: which
third-party domains were contacted, which of those are known trackers, which
cookies were set and how long they live, which fingerprinting functions fired.
The profiling-cookie rule described earlier is applied here. One improvement
over the original method: cookies set by JavaScript never appear in response
headers, so the system also reads the browser's cookie store directly and
merges anything the headers missed, removing duplicates.

In parallel, another component finds and downloads the site's privacy and
cookie policies and saves them as clean text.

## Phase three: making the judgement

Now the three sources come together, once for each compliance dimension. A
dimension is a specific question — for example, "does this site fire tracking
requests before obtaining consent?"

First, the law is retrieved. This happens two ways at once. The dimension
declares which articles are known to be relevant, and those are fetched
directly by their metadata, deterministically. Alongside that, a similarity
search runs over the vector database, filtered to the right regulation and
requirement type, in case something relevant was not anticipated. The
deterministic results are placed first. The reason for that belt-and-braces
approach is a real failure described in Part Six.

Second, the policy text is loaded in full. It is not summarised or chunked,
because a summary might drop the one sentence that matters.

Third, the behavioural evidence is filtered down to only what this dimension
is entitled to consider, so the model never sees evidence it should not be
reasoning from.

These three go into an IRAC-structured prompt with a hard instruction: quote
only from the legal text supplied here, never from memory. The model returns a
structured answer containing a score from zero to one hundred, a verdict, a
confidence value, the article it considers breached with a quotation, the
policy sentence it relies on with a quotation, the specific behaviour observed,
the type of discrepancy, a plain English explanation, and a recommended fix.
The temperature is set to zero so that running the same audit twice gives the
same answer, which matters for evaluation.

Before any of that happens, two guards can stop it. If the capture is
degenerate — almost no requests, no interface elements, which is what
bot-blocking looks like — the system refuses to score at all. And if there is
neither a policy nor any relevant observed behaviour for a dimension, the
verdict is forced to "not addressed" without the model being called, because
there is genuinely nothing to judge.

Finally the dimension scores are combined into an overall figure, weighted by
severity, with abstentions excluded, and rendered as a report.

---

# Part Four: The decisions, and how to defend them

This is the part to rehearse most. In a viva, explaining what you built is the
easy half; explaining why you built it that way, and what you rejected, is the
half that carries marks.

**Why use a language model at all, rather than rules?** Because the two halves
of the problem are different in kind. The behavioural half is mechanical, and
it *is* handled by rules — the profiling-cookie test is deterministic code with
no model involved. The other half is not mechanical. Deciding whether a
particular sentence in a policy adequately discloses a particular observed
practice is a reading-comprehension problem. No regular expression decides
whether "we may work with selected partners" adequately discloses sharing data
with fifteen named advertising companies. That judgement is what the model is
for.

**Why retrieval-augmented generation rather than fine-tuning a model on
privacy law?** Three reasons. First, hallucinated citations: an ungrounded
model will confidently invent article numbers, and a compliance finding that
cites a non-existent article is worse than useless. Second, auditability: with
retrieval you can show precisely which text the model was given, which makes
every judgement checkable after the fact. Third, and most concretely, the law
changes. There is a real example in this project: the UK amended its cookie
rules in February twenty twenty six, moving analytics cookies from requiring
opt-in consent to an opt-out basis under certain conditions. Because the law
lives in a database rather than in the model's weights, the system picked up
the amended rule with no retraining at all. A fine-tuned model would still be
applying the old rule and would be confidently wrong.

**Why this particular embedding model?** This is the best story in the
project, because the first choice was wrong and the evidence proved it. The
initial choice was legal-BERT, a model trained on legal text, chosen because
Polisis had shown domain-specific embeddings help. When retrieval was tested,
it was close to random: a query about cookie consent ranked Indian data
protection *penalty* clauses above the GDPR article on consent, and the
similarity scores were nearly identical for everything, around zero point
seven two regardless of content. The diagnosis is that legal-BERT is a raw
masked language model. It was never trained to produce sentence-level
embeddings where distance means similarity of meaning. Swapping it for a
model that *was* trained that way fixed retrieval immediately. The lesson,
stated in the paper, is that domain vocabulary does not compensate for missing
sentence-level training. This is a good answer to give because it shows a
decision changed on measurement rather than intuition.

**Why chunk statutes by article rather than by size?** Because the output has
to cite and quote a specific provision, and a chunk that spans half of one
article and half of another cannot support a valid citation.

**Why a small, cheap model for scoring?** Cost and structure. There are up to
fifteen dimensions per site, so bulk scoring needs to be cheap, and the API
mode that guarantees valid structured output matters more than raw
intelligence for this task. The scorer detects the provider from the model
name, so switching to a different vendor's model is a one-word change. The
formal comparison — running candidates against the LegalBench privacy tasks —
is acknowledged as remaining work rather than claimed as done.

**Why temperature zero?** Reproducibility. If the same input produces
different verdicts on different runs, no before-and-after comparison means
anything, and the evaluation collapses.

**Why not simply reuse the existing tools, CookieCheck or the Bouhoula
crawler?** Because they answer a different question. They are measurement
instruments built to produce population statistics: what fraction of sites
violate the rule. This project answers a per-site question: what is *this*
site doing wrong, under which specific article, contradicted by which specific
sentence of its own policy. That requires structured evidence about each
individual site, which those pipelines discard as soon as they have counted
it. What is reused is their validated rules, cited at the point of use in the
code — which is a stronger form of reuse than running someone's script.

---

# Part Five: What the testing showed

Twenty websites were audited, spanning six sectors and four jurisdictions,
deliberately including two sites known to use bot protection so that the
failure path would be exercised rather than avoided.

Fifteen produced scored reports. Two were refused because the capture was
degenerate — the sites blocked the automated browser and served effectively
empty pages. Two more exceeded the time budget for collection. One produced a
verdict of insufficient data because neither a policy nor relevant behaviour
could be obtained. So the capture failure rate is ten percent, and the system
declines to give an opinion on a quarter of attempts. Declining is the
intended behaviour and worth defending in those terms: a tool that scores an
empty capture is producing confident findings about nothing.

By sector, the government site scored highest and e-commerce lowest, with news
media in the lower half. That ordering broadly matches the published
literature, where government sites are the most compliant and news media the
least. It should not be over-read: several sectors have only one site in them.

One finding is more interesting than the sector table. The cookie-based test
that the earlier literature relies on turned out to be the *weakest* of the
three signals. Only three sites failed the pre-consent cookie test, because
most sites now run consent platforms that correctly withhold cookies. But ten
sites failed the broader tracking test, because the *requests* to tracking
companies still fire before consent even when no cookie is stored, and seven
failed on third-party disclosure. The implication is that a cookie-only
methodology would substantially under-report the current state of the web,
which is a genuine research point.

The scores clustered on round numbers — only seven distinct values across
fifteen sites — because the model anchors on the round values of the scoring
rubric. The honest conclusion, stated in the paper, is that the scores should
be used to rank sites and not treated as precise measurements.

---

# Part Six: Verification, and the failures found along the way

This section answers the question an examiner is most likely to press on: how
do you know the model is not simply making things up?

The answer is a separate verification tool that re-checks every claim in every
report against the raw material it should have come from. Critically, it
involves no language model at all. It is string matching and structural rules,
which means it cannot itself hallucinate. For this to be possible, the scorer
records, with every verdict, exactly which legal articles were retrieved and
the exact text that was placed in the prompt.

Five checks run on each verdict. Was the cited article actually among those
retrieved? Does the quoted legal requirement appear word for word in the text
that was supplied? Does the quoted policy sentence appear word for word in the
scraped policy? Does every domain, cookie name and count mentioned in the
finding exist in the telemetry? And do the internal rules hold — for example,
that an abstention carries no breach citation.

Across fifteen reports the tool raised five flags, and the grounding rate —
the proportion of judgements where every claim traced back to its source —
was about eighty seven percent. The critical number is that **zero** claims
were fabricated behavioural evidence. Every domain, every cookie and every
fingerprinting call named in every report was genuinely present in the
recorded traffic.

Now the failures, which are worth knowing in detail because they demonstrate
the testing worked.

**The first failure was over-condemnation.** In an early run, the system
returned a total fail with maximum confidence on a dimension where no
profiling cookies had been found. Reading the explanation revealed two
problems. The model had invented cookie installations that were not in the
evidence, and it had misread a line in the prompt. That line said "consent
interaction: none", which described *our crawler's* deliberate protocol of not
clicking anything — and the model interpreted it as the site having no consent
mechanism. Both were fixed by rewriting the prompt: an explicit note that the
no-interaction protocol is a property of the audit rather than a failing of
the site, and a hard rule that when no evidence of a given type was observed,
no behavioural violation may be asserted. On re-running, the verdict became a
measured partial with the behavioural evidence field correctly empty.

**The second failure was a retrieval near-miss.** A verdict about disclosing
third parties cited GDPR article nineteen, which concerns notifying recipients
about rectification and erasure, instead of article thirteen, which is the one
requiring disclosure of recipients. What is instructive is that the model did
nothing wrong: it had been told to cite only the retrieved text, and it obeyed.
The retrieval had ranked the wrong article first because both articles contain
the word "recipients" in similar phrasing. The fix was the deterministic
anchoring described earlier. The deeper point, and it is a good one to make in
the viva, is that grounding moves failures from the generation step, which is
opaque, to the retrieval step, which is inspectable and fixable.

**The third failure was garbage input.** A bot-blocked site produced a capture
with one request and no interface elements, and the system issued confident
failures based on nothing, treating a policy it had failed to fetch as proof
that no policy existed. This produced both guards: the capture sanity check
and the insufficiency rule.

**The fourth was found by the batch itself.** On sites where no policy could
be retrieved, the model was asserting that practices had not been disclosed —
an assertion about a document it had never seen. Non-disclosure cannot be
established from an unread policy, so this is now blocked.

There is one more admission worth making before an examiner finds it. Two
defects were found in the *verification tool* itself. It was treating
fingerprinting function names as if they were internet domains, and it was
mishandling quotations containing an ellipsis, checking them after removing
the very marker that indicated the elision. Both made the model look worse
than it was. Correcting them raised the measured grounding rate substantially.
The general lesson is that when you build an instrument to measure a system,
the instrument itself needs validating — and volunteering this before being
asked is much stronger than conceding it afterwards.

---

# Part Seven: The limitations, stated honestly

There are four, and the first is the most important.

**Policy retrieval coverage distorts the results more than site behaviour
does.** Sites where the scraper failed to find any policy scored close to zero
on average, while sites with policies averaged in the low thirties. That gap
of roughly thirty three points is caused by the auditing pipeline's own
retrieval failures, not by the sites being worse. Two causes were identified:
some organisations host their policies on a parent company's domain, which the
scraper's same-domain preference misses, and some sites render policy links
only after JavaScript executes. The correct response is to report those sites
separately rather than let them drag the averages, and that is what the paper
does. This is the single best thing to volunteer when asked about weaknesses,
because it is a limitation of the researcher's own tool, found by the
researcher's own instrumentation.

**Bot protection bounds coverage.** Ten percent of sites could not be captured
at all. Because degenerate captures are refused rather than scored, this shows
up as reduced coverage rather than as wrong answers, which is the better
failure mode — but the sites most likely to track aggressively are also the
ones most likely to block automated auditing.

**There is no independent ground truth yet.** The evaluation demonstrates that
findings are grounded in the evidence. It does not demonstrate that a lawyer
would agree with the verdicts. Establishing that requires hand annotation
against the article text, computing precision and recall per dimension. It is
the principal item of remaining work and it is stated as a threat to validity
rather than glossed over.

**Jurisdiction matters more than a single-country study would reveal.** The
GDPR applies across the European Union, but the cookie rules come from a
directive that each country transposes into its own law. An early version of
the batch scored Irish websites against the United Kingdom's regulations,
which do not apply in Ireland — Ireland has its own statutory instrument from
twenty eleven, with the operative provision in regulation five. The framework
now selects instruments by jurisdiction. This is worth raising proactively
because it is a mistake that any cross-border compliance tool assuming a
single ePrivacy text would make, and it is invisible in a single-country
evaluation.

---

# Part Eight: Questions and answers, for rapid-fire practice

**What is the contribution, in one sentence?** A framework that combines
retrieved legal text, the site's written policy and live runtime telemetry in
a single judgement per compliance dimension, which no prior system does for
the web.

**How do you know the model is not hallucinating?** Because every claim is
mechanically re-checked against the artefacts it should have come from, by a
tool that uses no language model and therefore cannot fabricate. Across
fifteen reports it found no invented behavioural evidence.

**What is the weakest part of the work?** Policy retrieval coverage, which
accounts for about thirty three points of score difference; and the absence of
independent legal ground truth.

**Which parts of the code are yours?** The whole pipeline: the browser
instrumentation, the evidence extractor, the legal chunker and ingestion, the
retriever, the scorer, the report builder, the verification tool and the batch
harness. What is adopted is validated *rules* from published work, cited at
the point of use — the cookie definition, the discrepancy vocabulary, the
prompt structure, the reporting language. What is third-party is the two
tracker blocklists and standard libraries.

**Is twenty sites enough?** No, and the paper says so. It is enough to expose
pipeline limitations. It is not enough to make claims about sector-level
compliance rates, particularly where a sector has one site.

**Why do your scores cluster on round numbers?** Because the model anchors on
the rubric's values. The consequence is that scores should rank sites rather
than measure distances, which is stated explicitly.

**What happens if the vector database is empty or the model returns
malformed output?** Retrieval falls back to an unfiltered search rather than
failing; malformed output is caught by a parser that clamps out-of-range
values, validates the verdict against the allowed set, and degrades to an
error verdict rather than crashing the run.

**Could this be used to make a legal decision?** No, and it deliberately never
claims to. Every finding is phrased as a *potential* issue, following the
convention established by the MAPS work. It produces evidence for a human
reviewer, and the reviewer decides.

**How would you scale it to a hundred thousand sites?** Parallel collection,
which the Bouhoula work demonstrates; cheap-model-first tiering, which MAPS
demonstrates; and caching the legal retrieval per dimension, since the law
does not change between sites.

**What would you do next?** In order: annotate a sample by hand to get real
accuracy numbers; add consent-banner interaction so the system can test
whether tracking continues after an explicit refusal, which is the strongest
test in the literature; fix cross-domain policy discovery; and then the novel
extension, which is auditing what a site collects *after* login and comparing
that against the scope of the consent that was actually given. No reviewed
paper does that for the web.

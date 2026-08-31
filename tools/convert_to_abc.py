import json
import math
import random
import re
import unicodedata
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
SEED = 7312026

STOP = {
    'koji','koja','koje','kojeg','kojem','kojoj','kojim','kojih','kako','kakav','kakva','kakvo','koliko','gdje','kada','kad','tko','sto','sta','je','su','se','u','na','iz','za','od','do','s','sa','i','ili','a','te','pa','po','pod','nad','bio','bila','bilo','bili','ima','imao','imala','naziva','zove','poznat','poznata','poznato','poznati','sljedecih','sljedece','sljedeci','prema','ovom','ovoj','ovoga','jedan','jedna','jedno','prvi','prva','prvo','godine','godina','godini','film','igri','igre','pitanju'
}

TAG_RULES = {
    'person': ['glumac','glumica','redatelj','redateljica','pisac','spisatelj','knjizevnik','pjesnik','skladatelj','pjevac','pjevacica','predsjednik','car','kralj','kraljica','vojskovoda','general','znanstvenik','fizicar','kemicar','biolog','istrazivac','moreplovac','nogometas','igrac','trener','lik','junak','junakinja','autor'],
    'place': ['grad','drzav','zemlj','otok','rijek','jezer','planin','more','ocean','kontinent','pokrajin','regij','poluotok','tjesnac','zaljev','pustinj','prijestolnic','glavni grad'],
    'country': ['drzav','zemlj'],
    'city': ['grad','prijestolnic','glavni grad'],
    'work': ['film','roman','knjig','djelo','pjesm','album','serij','igra','videoigr','opera','drama','strip'],
    'organization': ['klub','momcad','reprezentacij','tvrtk','organizacij','strank','dinastij','carstvo','kraljevstvo'],
    'sport': ['sport','liga','prvenstv','turnir','utakmic','gol','igrac','klub'],
    'science': ['element','kemij','fizik','biolog','planet','zvijezd','atom','molekul','jedinic','simbol'],
    'animal': ['zivotinj','sisav','ptic','rib','gmaz','kukac','vrst'],
    'plant': ['biljk','stabl','cvijet','flora'],
    'history': ['rat','bitk','car','kralj','predsjednik','dinastij','stoljec','povijest'],
    'ship': ['brod','jedrenjak','podmornic','plovil'],
    'award': ['nagrad','oscar','nobel','trofej','medalj'],
}

NUM_RE = re.compile(r'^\s*[-+]?\d+(?:[.,]\d+)?\s*(?:%|km|m|cm|mm|kg|g|l|ml|s|min|h)?\s*$', re.I)
YEAR_RE = re.compile(r'\b(1[0-9]{3}|20[0-9]{2})\b')


def ascii_text(s):
    s = unicodedata.normalize('NFKD', str(s))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def norm(s):
    s = ascii_text(s)
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return ' '.join(s.split())


def tokens(s):
    return {t for t in norm(s).split() if len(t) >= 3 and t not in STOP}


def tags(question):
    q = norm(question)
    out = set()
    for tag, stems in TAG_RULES.items():
        if any(stem in q for stem in stems):
            out.add(tag)
    if any(x in q for x in ['koje godine','kojoj godini','godine je','godina je','koje je godine']):
        out.add('year')
    if 'koliko' in q:
        out.add('number')
    return out


def answer_kind(answer):
    a = str(answer).strip()
    na = norm(a)
    if NUM_RE.match(a):
        if re.fullmatch(r'(1[0-9]{3}|20[0-9]{2})', na):
            return 'year'
        return 'number'
    if len(a) <= 3 and a.upper() == a and any(c.isalpha() for c in a):
        return 'acronym'
    words = a.split()
    if 2 <= len(words) <= 5 and sum(1 for w in words if w[:1].isupper()) >= 2:
        return 'named'
    if len(words) == 1 and words[0][:1].isupper():
        return 'proper'
    return 'text'


def too_similar(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return True
    if na == nb or na in nb or nb in na:
        return True
    sa, sb = set(na.split()), set(nb.split())
    if sa and sb and len(sa & sb) / max(1, min(len(sa), len(sb))) >= 0.8:
        return True
    return False


def parse_number(ans):
    m = re.search(r'[-+]?\d+(?:[.,]\d+)?', str(ans))
    if not m:
        return None
    return float(m.group(0).replace(',', '.'))


def format_like(original, value):
    s = str(original).strip()
    unit = re.sub(r'^\s*[-+]?\d+(?:[.,]\d+)?\s*', '', s)
    if abs(value - round(value)) < 1e-9:
        n = str(int(round(value)))
    else:
        n = ('%.2f' % value).rstrip('0').rstrip('.')
        if ',' in s and '.' not in s:
            n = n.replace('.', ',')
    return (n + ((' ' + unit) if unit and not unit.startswith('%') else unit)).strip()


def numeric_distractors(question, correct, rng):
    x = parse_number(correct)
    if x is None:
        return []
    qn = norm(question)
    is_year = bool(re.fullmatch(r'\s*(1[0-9]{3}|20[0-9]{2})\s*', str(correct))) or 'year' in tags(question)
    vals = []
    if is_year:
        steps = [1,2,3,4,5,10,20,25,50]
        rng.shuffle(steps)
        for st in steps:
            vals.extend([x-st, x+st])
    elif abs(x) <= 12 and abs(x-round(x)) < 1e-9:
        for st in [1,2,3]:
            vals.extend([x-st, x+st])
    elif abs(x) <= 100 and abs(x-round(x)) < 1e-9:
        for st in [1,2,5,10]:
            vals.extend([x-st, x+st])
    else:
        for factor in [0.9,1.1,0.8,1.2,0.95,1.05]:
            vals.append(x*factor)
    out=[]
    rng.shuffle(vals)
    for v in vals:
        if v < 0 and x >= 0:
            continue
        fv = format_like(correct, v)
        if not too_similar(correct, fv) and fv not in out:
            out.append(fv)
        if len(out) == 2:
            break
    return out


def question_score(q1, q2, t1, t2):
    tok1, tok2 = tokens(q1), tokens(q2)
    inter = tok1 & tok2
    union = tok1 | tok2
    score = 0.0
    if union:
        score += 8.0 * len(inter) / len(union)
    score += 2.5 * len(t1 & t2)
    # Encourage matching interrogative/domain wording.
    n1, n2 = norm(q1), norm(q2)
    for cue in ['glumac','glumica','film','grad','drzav','rijek','otok','car','kralj','predsjednik','roman','autor','pjesm','album','klub','nogometas','igrac','brod','planet','element','zivotinj','biljk','koliko','godine']:
        if cue in n1 and cue in n2:
            score += 2.0
    return score


def choose_text_distractors(item, records, all_records, rng):
    correct = item['_correct']
    q = item.get('question','')
    qt = item['_tags']
    kind = item['_kind']
    candidates=[]

    def add_pool(pool, same_file_bonus):
        for other in pool:
            cand = other['_correct']
            if too_similar(correct, cand):
                continue
            okind = other['_kind']
            ot = other['_tags']
            if qt and ot and not (qt & ot):
                continue
            # Keep broad answer shape compatible.
            if kind in ('named','proper') and okind not in ('named','proper'):
                continue
            if kind == 'acronym' and okind != 'acronym':
                continue
            if kind == 'text' and okind in ('number','year'):
                continue
            score = question_score(q, other.get('question',''), qt, ot) + same_file_bonus
            # Penalize implausibly different answer lengths.
            lc, lo = max(1,len(correct)), max(1,len(cand))
            score -= abs(math.log(lc/lo)) * 0.35
            candidates.append((score, rng.random(), cand))

    add_pool(records, 1.5)
    if len(candidates) < 8:
        add_pool(all_records, 0.0)
    candidates.sort(reverse=True)
    out=[]
    for _,__,cand in candidates:
        if any(too_similar(cand, x) for x in out):
            continue
        out.append(cand)
        if len(out)==2:
            return out
    return out


def position_plan(n, rng):
    counts = [n//3]*3
    for i in range(n%3):
        counts[i]+=1
    pos=[]
    for i,c in enumerate(counts):
        pos.extend([i]*c)
    rng.shuffle(pos)
    return pos, counts


def load_all(files):
    file_records={}
    all_records=[]
    for f in files:
        data=json.loads(f.read_text(encoding='utf-8-sig'))
        if not isinstance(data,list):
            raise ValueError(f'{f.name}: root is not an array')
        recs=[]
        for idx,obj in enumerate(data):
            if not isinstance(obj,dict):
                raise ValueError(f'{f.name} #{idx+1}: item is not an object')
            ans=obj.get('answers')
            if not isinstance(ans,list) or not ans or not str(ans[0]).strip():
                raise ValueError(f'{f.name} #{idx+1}: missing canonical first answer')
            rec=dict(obj)
            rec['_file']=f.name
            rec['_idx']=idx
            rec['_correct']=str(ans[0]).strip()
            rec['_tags']=tags(obj.get('question',''))
            rec['_kind']=answer_kind(rec['_correct'])
            recs.append(rec)
            all_records.append(rec)
        file_records[f]=recs
    return file_records,all_records


def main():
    files=sorted(p for p in ROOT.glob('*.json') if p.name != 'abc_conversion_report.json')
    file_records, all_records = load_all(files)
    report=[]
    total=0

    for f,recs in file_records.items():
        rng=random.Random(SEED + sum(map(ord,f.name)))
        positions, planned_counts = position_plan(len(recs), rng)
        converted=[]
        actual=Counter()
        weak=[]

        for i,item in enumerate(recs):
            correct=item['_correct']
            q=item.get('question','')
            if item['_kind'] in ('number','year'):
                distractors=numeric_distractors(q, correct, rng)
            else:
                distractors=choose_text_distractors(item,recs,all_records,rng)

            if len(distractors)<2:
                # Last-resort same-file pool, still shape-aware where possible.
                pool=[r['_correct'] for r in recs if not too_similar(correct,r['_correct'])]
                rng.shuffle(pool)
                for cand in pool:
                    if cand not in distractors and not any(too_similar(cand,x) for x in distractors):
                        distractors.append(cand)
                    if len(distractors)==2:
                        break

            if len(distractors)<2:
                raise ValueError(f'{f.name} #{i+1}: could not create two distractors')

            p=positions[i]
            opts=distractors[:2]
            rng.shuffle(opts)
            opts.insert(p,correct)
            letter='ABC'[p]
            actual[letter]+=1

            out={}
            for k,v in item.items():
                if k.startswith('_') or k in ('answers','correctAnswer'):
                    continue
                if k=='image':
                    out['answers']=opts
                    out['correctAnswer']=letter
                out[k]=v
            if 'answers' not in out:
                out['answers']=opts
                out['correctAnswer']=letter
            converted.append(out)

            # Flag low lexical semantic confidence for report, without blocking conversion.
            if item['_kind'] not in ('number','year'):
                sc=max(question_score(q,r.get('question',''),item['_tags'],r['_tags']) for r in recs if r is not item) if len(recs)>1 else 0
                if sc < 1.0:
                    weak.append(i+1)

        f.write_text(json.dumps(converted,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        total += len(converted)
        report.append({
            'file':f.name,
            'questions':len(converted),
            'correct_positions':dict(actual),
            'low_similarity_review_candidates':weak[:100],
            'low_similarity_count':len(weak),
        })

    (ROOT/'abc_conversion_report.txt').write_text(
        'ABC conversion completed\nTotal questions: %d\n\n%s\n' % (
            total,
            '\n'.join(f"{r['file']}: {r['questions']} questions | A={r['correct_positions'].get('A',0)} B={r['correct_positions'].get('B',0)} C={r['correct_positions'].get('C',0)} | review={r['low_similarity_count']}" for r in report)
        ),encoding='utf-8')
    print(f'Converted {total} questions in {len(files)} JSON files.')

if __name__=='__main__':
    main()

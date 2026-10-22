"""Devanagari word -> the Roman spelling the rule banks in this repo already match.

Format: ``roman: spelling spelling ...`` (several Devanagari spellings of the same word). Lookup
keys are compared after ``translit.canon`` (nukta removed, chandrabindu = anusvara), so ``फोन`` and
``फ़ोन``, ``पाँच`` and ``पांच`` are one entry. The Roman side uses the spellings of
``lifestate/capture.py``, ``savings/`` and ``calls/understand.py`` (kal, shaam, baje, interview,
rupaye ...), because those regexes are the reason this table exists.
"""

from __future__ import annotations

from friday.lang_dev.translit import canon

_TABLE = """
# --- days, dates, time
kal: कल
aaj: आज
parso: परसों परसो
narso: नरसों नरसो
subah: सुबह
savere: सवेरे
shaam: शाम
dopahar: दोपहर
raat: रात
baje: बजे बजकर
sawa: सवा
saade: साढ़े साढे
paune: पौने
dedh: डेढ़ डेढ
dhai: ढाई
ghante: घंटे घण्टे
ghanta: घंटा घण्टा
minute: मिनट मिनिट
baad: बाद
tak: तक
se: से
ko: को
mein: में
me: मे
par: पर
pe: पे
agle: अगले
agla: अगला
hafte: हफ्ते हफ़्ते
hafta: हफ्ता हफ़्ता
mahine: महीने
mahina: महीना
saal: साल
din: दिन
roz: रोज़ रोज
rozana: रोज़ाना रोजाना
har: हर
tarikh: तारीख तारीख़
date: डेट
somvar: सोमवार
mangalvar: मंगलवार
budhvar: बुधवार
guruvar: गुरुवार वीरवार
shukravar: शुक्रवार
shanivar: शनिवार
ravivar: रविवार
itwar: इतवार
january: जनवरी
february: फरवरी फ़रवरी
march: मार्च
april: अप्रैल
may: मई
june: जून
july: जुलाई
august: अगस्त
september: सितंबर सितम्बर
october: अक्टूबर अक्तूबर
november: नवंबर नवम्बर
december: दिसंबर दिसम्बर
month end: महीने के अंत | महीने के आखिर | महीने का अंत
# --- grammar
hai: है
hain: हैं
hoon: हूँ हूं
ho: हो
hoga: होगा
hogi: होगी
tha: था
thi: थी
the: थे
ka: का
ki: की कि
ke: के
kya: क्या
kab: कब
kaun: कौन
kaise: कैसे
kitna: कितना
kitne: कितने
kitni: कितनी
kahan: कहाँ कहां
kyun: क्यों क्यूँ
nahi: नहीं नही
nahin: नहीँ
haan: हाँ हां
han: हॅं
ji: जी
aur: और
ya: या
bhi: भी
toh: तो
to: तो
lekin: लेकिन
magar: मगर
main: मैं
mai: मै
mujhe: मुझे
mera: मेरा
meri: मेरी
mere: मेरे
hamara: हमारा
tumhe: तुम्हें तुम्हे
tum: तुम
aap: आप
aapka: आपका
aapko: आपको
mujhko: मुझको
usko: उसको
unko: उनको
isko: इसको
yeh: यह ये
woh: वह वो
iss: इस
uss: उस
is: इस
us: उस
liye: लिए लिये
paas: पास
saath: साथ
sab: सब
sabko: सबको
sabhi: सभी
saare: सारे
saari: सारी
poora: पूरा
puri: पूरी
kuch: कुछ
koi: कोई
bahut: बहुत
thoda: थोड़ा थोडा
zyada: ज़्यादा ज्यादा
kam: कम
abhi: अभी
phir: फिर
dobara: दोबारा दुबारा
wapas: वापस
pehle: पहले
baare: बारे
sa: सा
si: सी
se: से
wala: वाला
wali: वाली
wale: वाले
jaldi: जल्दी
zaroor: ज़रूर जरूर
zaroori: ज़रूरी जरूरी
theek: ठीक
sahi: सही
galat: गलत ग़लत
accha: अच्छा
achha: अच्छा
shukriya: शुक्रिया
dhanyavaad: धन्यवाद
namaste: नमस्ते
please: प्लीज़ प्लीज
sorry: सॉरी
ok: ओके
# --- verbs
kar: कर
karo: करो
karna: करना
karni: करनी
karne: करने
karke: करके
kardo: कर्दो
karna hai: करना है | करनी है
kijiye: कीजिए कीजिये
kariye: करिए करिये
karein: करें
kare: करे
karta: करता
karti: करती
kiya: किया
kiye: किए किये
do: दो
dena: देना
dijiye: दीजिए दीजिये
dedo: देदो
diya: दिया
lo: लो
lena: लेना
le: ले
jao: जाओ
jana: जाना
jaana: जाना
jaa: जा
aao: आओ
aana: आना
aa: आ
raha: रहा
rahi: रही
rahe: रहे
bata: बता
batao: बताओ
bataiye: बताइए बताइये
bata do: बता दो | बता दीजिए
bol: बोल
bolo: बोलो
boliye: बोलिए बोलिये
kehna: कहना
keh: कह
puchho: पूछो
poocho: पूछो
puch: पूछ
poochna: पूछना
dikhao: दिखाओ
dikha: दिखा
bhejo: भेजो
bhej: भेज
bhejna: भेजना
rakho: रखो
rakh: रख
rakhna: रखना
chahiye: चाहिए चाहिये
sakti: सकती
sakta: सकता
sakte: सकते
padega: पड़ेगा
hoga: होगा
milega: मिलेगा
bhool: भूल
bhul: भूल
jao: जाओ
hata: हटा
hatao: हटाओ
hata do: हटा दो | हटा दीजिए | हटा दे
mita: मिटा
mitao: मिटाओ
mita do: मिटा दो | मिटा दीजिए
nikal: निकाल
nikal do: निकाल दो | निकाल दीजिए
band: बंद बन्द
bas: बस
ruko: रुको रूको
rok: रोक
jodo: जोड़ो जोडो
jod: जोड़
badal: बदल
badlo: बदलो
yaad: याद
dilana: दिलाना
dilao: दिलाओ
dila: दिला
suna: सुना
mat: मत
mat poocho: मत पूछो | मत पूछना | मत पूछिए | मत पुछो
dhundh: ढूंढ ढूँढ
dhundo: ढूंढो ढूँढो
book: बुक
# --- people
mummy: मम्मी मॉम
mom: मॉम
maa: माँ मां मा
papa: पापा
pitaji: पिताजी
dad: डैड
bhaiya: भैया
bhai: भाई
didi: दीदी
behen: बहन
bhabhi: भाभी
dadi: दादी
nani: नानी
dada: दादा
nana: नाना
chacha: चाचा
chachi: चाची
mama: मामा
mami: मामी
bua: बुआ
beta: बेटा
beti: बेटी
dost: दोस्त
yaar: यार
wife: वाइफ
biwi: बीवी
husband: हसबैंड
pati: पति
patni: पत्नी
sasur: ससुर
saas: सास
plumber: प्लंबर प्लम्बर
electrician: इलेक्ट्रीशियन इलेक्ट्रिशियन
driver: ड्राइवर
cook: कुक
maid: मेड
bai: बाई
kaamwali: कामवाली
carpenter: कारपेंटर
mistri: मिस्त्री
painter: पेंटर
tutor: ट्यूटर
landlord: लैंडलॉर्ड
mechanic: मैकेनिक
doodhwala: दूधवाला
maali: माली
watchman: वॉचमैन
doctor: डॉक्टर डाक्टर
dentist: डेंटिस्ट डेन्टिस्ट
nurse: नर्स
teacher: टीचर
principal: प्रिंसिपल
school: स्कूल
college: कॉलेज
office: ऑफिस ऑफ़िस
society: सोसाइटी
# --- things / places / English words typed in Devanagari
phone: फोन फ़ोन
call: कॉल कौल
missed call: मिस्ड कॉल | मिस कॉल
callback: कॉलबैक
message: मैसेज मेसेज
msg: मैसेज
card: कार्ड
credit: क्रेडिट
debit: डेबिट
bill: बिल
bills: बिल्स
bank: बैंक
account: अकाउंट
wallet: वॉलेट
cards: कार्ड्स
reward: रिवॉर्ड
cashback: कैशबैक
points: पॉइंट्स
statement: स्टेटमेंट
due: ड्यू
payment: पेमेंट
pay: पे
paid: पेड
recharge: रिचार्ज
prepaid: प्रीपेड
postpaid: पोस्टपेड
emi: ईएमआई
rent: रेंट
kiraya: किराया
premium: प्रीमियम
insurance: इंश्योरेंस इन्शुरन्स
policy: पॉलिसी
electricity: इलेक्ट्रिसिटी
bijli: बिजली
paani: पानी
gas: गैस
wifi: वाईफाई वाईफ़ाई वाई-फाई
broadband: ब्रॉडबैंड
internet: इंटरनेट
dth: डीटीएच
petrol: पेट्रोल
diesel: डीज़ल डीजल
fuel: फ्यूल
cng: सीएनजी
restaurant: रेस्टोरेंट रेस्तरां रेस्टोरेन्ट
dinner: डिनर
lunch: लंच
breakfast: ब्रेकफास्ट
cafe: कैफे कैफ़े
hotel: होटल
food: फूड
order: ऑर्डर
delivery: डिलीवरी
grocery: ग्रोसरी
sabzi: सब्ज़ी सब्जी
doodh: दूध
atta: आटा
medicine: मेडिसिन
dawai: दवाई दवा
dawa: दवा
pharmacy: फार्मेसी
chemist: केमिस्ट
hospital: हॉस्पिटल अस्पताल
clinic: क्लिनिक
appointment: अपॉइंटमेंट अपॉइन्टमेंट
checkup: चेकअप
interview: इंटरव्यू इंटरव्यु इन्टरव्यू
meeting: मीटिंग
meet: मीट
presentation: प्रेजेंटेशन प्रेज़ेंटेशन
demo: डेमो
review: रिव्यू
client: क्लाइंट
standup: स्टैंडअप
sync: सिंक
flight: फ्लाइट
train: ट्रेन
bus: बस
cab: कैब
taxi: टैक्सी
auto: ऑटो
airport: एयरपोर्ट
station: स्टेशन
ticket: टिकट
tickets: टिकट्स
trip: ट्रिप
movie: मूवी
film: फिल्म
party: पार्टी
function: फंक्शन
birthday: बर्थडे
anniversary: एनिवर्सरी
shaadi: शादी
puja: पूजा
pooja: पूजा
gym: जिम
class: क्लास
haircut: हेयरकट
salon: सैलून सलून
parlour: पार्लर
laptop: लैपटॉप
mobile: मोबाइल मोबाईल
tv: टीवी
fridge: फ्रिज
ac: एसी
shopping: शॉपिंग
online: ऑनलाइन
sale: सेल
subscription: सब्सक्रिप्शन
fees: फीस
tuition: ट्यूशन
customer care: कस्टमर केयर | कस्टमर-केयर
customer support: कस्टमर सपोर्ट | कस्टमर सपोर्ट
helpline: हेल्पलाइन
support: सपोर्ट
complaint: कंप्लेंट कम्प्लेंट
refund: रिफंड
booking: बुकिंग
table: टेबल
quote: कोट
price: प्राइस
rate: रेट
budget: बजट
discount: डिस्काउंट
menu: मेनू मीनू
help: हेल्प
status: स्टेटस
stop: स्टॉप
delete: डिलीट
remove: रिमूव
cancel: कैंसल
export: एक्सपोर्ट
data: डेटा
reminder: रिमाइंडर
remind: रिमाइंड
alert: अलर्ट
brief: ब्रीफ
google: गूगल
gmail: जीमेल
calendar: कैलेंडर कैलेन्डर
connect: कनेक्ट
disconnect: डिस्कनेक्ट
whatsapp: व्हाट्सएप व्हाट्सऐप वॉट्सऐप
voice note: वॉइस नोट | वॉयस नोट | वॉइस मैसेज
voice: वॉइस
text: टेक्स्ट
audio: ऑडियो
yes: यस
no: नो
ok: ओके
# --- banks, merchants, networks (as bank/merchant tables spell them)
hdfc: एचडीएफसी
sbi: एसबीआई एस बी आई
icici: आईसीआईसीआई
axis: एक्सिस एक्सिस्
kotak: कोटक
idfc: आईडीएफसी
indusind: इंडसइंड
yes bank: येस बैंक | यस बैंक
rbl: आरबीएल
amex: अमेक्स एमेक्स
hsbc: एचएसबीसी
pnb: पीएनबी
bob: बीओबी
citi: सिटी
visa: वीज़ा वीजा
mastercard: मास्टरकार्ड | मास्टर कार्ड
rupay: रुपे रूपे
regalia: रेगालिया रीगालिया
cashback: कैशबैक
millennia: मिलेनियल्स मिलेनिया
swiggy: स्विगी
zomato: ज़ोमैटो ज़ोमेटो जोमैटो
blinkit: ब्लिंकिट
zepto: ज़ेप्टो जेप्टो
bigbasket: बिगबास्केट
amazon: अमेज़न अमेज़ॉन अमेजन अमेज़न
flipkart: फ्लिपकार्ट
myntra: मिंत्रा
nykaa: नायका
meesho: मीशो
uber: उबर
ola: ओला
rapido: रैपिडो
irctc: आईआरसीटीसी
makemytrip: मेकमाईट्रिप
netflix: नेटफ्लिक्स
spotify: स्पॉटिफाई
hotstar: हॉटस्टार
bookmyshow: बुकमाईशो
paytm: पेटीएम
phonepe: फोनपे
gpay: जीपे
airtel: एयरटेल
jio: जियो
vodafone: वोडाफोन
bsnl: बीएसएनएल
lic: एलआईसी
bescom: बेस्कॉम
# --- money
rupaye: रुपये रुपए रूपये रुपया रूपए रु रूपया
rs: रु.
lakh: लाख
hazaar: हज़ार हजार
crore: करोड़ करोड
sau: सौ
paise: पैसे
kharcha: खर्चा खर्च
bachat: बचत
bachaya: बचाया
kitna: कितना
# --- bill / statement words
antim: अंतिम अन्तिम
tithi: तिथि
bhugtan: भुगतान
deya: देय
rakam: रकम
rashi: राशि
kul: कुल
baaki: बाकी
aadha: आधा
aadhi: आधी
# --- more people, places, things (added before the held-out set was written)
boss: बॉस
manager: मैनेजर
tauji: ताऊजी
mausi: मौसी
fufa: फूफा
jija: जीजा
saala: साला
cousin: कज़िन कजिन
uncle: अंकल
aunty: आंटी आन्टी
grandma: ग्रैंडमा
padosi: पड़ोसी पडोसी
pandit: पंडित
darzi: दर्जी
tailor: टेलर
dhobi: धोबी
security: सिक्योरिटी
guard: गार्ड
courier: कूरियर
ghar: घर
bazaar: बाज़ार बाजार
mandir: मंदिर
mall: मॉल
market: मार्केट
park: पार्क
atm: एटीएम
late: लेट
der: देर
khana: खाना
khaya: खाया
li: ली
liya: लिया
gaya: गया
gayi: गई गयी
aaunga: आऊँगा आऊंगा
aaungi: आऊँगी आऊंगी
pahunch: पहुँच पहुंच
nikal: निकल
nikla: निकला
kharid: खरीद
kharidna: खरीदना
udhaar: उधार
salary: सैलरी
total: टोटल
amount: अमाउंट
minimum: मिनिमम
link: लिंक
kaunsa: कौनसा
kaunsi: कौनसी
best: बेस्ट
croma: क्रोमा
iphone: आईफोन आइफोन
add: ऐड एड
menu: मेन्यू
magnus: मैग्नस
infinia: इनफिनिया इन्फिनिया
simplyclick: सिंपलीक्लिक सिम्पलीक्लिक
coral: कोरल
sapphiro: सफिरो
ascent: एसेंट
mileage: माइलेज
legend: लीजेंड
royale: रॉयल
league: लीग
wow: वाओ
platinum: प्लेटिनम
titanium: टाइटेनियम
signature: सिग्नेचर
premier: प्रीमियर
elite: एलीट
smart: स्मार्ट
mahindra: महिंद्रा
federal: फेडरल
dominos: डोमिनोज़ डोमिनोज
goibibo: गोइबिबो
cleartrip: क्लियरट्रिप
indigo: इंडिगो
dmart: डीमार्ट
jiomart: जियोमार्ट
reliance: रिलायंस
tata: टाटा
shell: शेल
apollo: अपोलो
headphones: हेडफोन हेडफ़ोन
earbuds: ईयरबड्स
camera: कैमरा
watch: वॉच
shoes: शूज़ शूज
kapde: कपड़े
joote: जूते
washing machine: वॉशिंग मशीन | वाशिंग मशीन
indian oil: इंडियन ऑयल |
bank of baroda: बैंक ऑफ बड़ौदा | बैंक ऑफ़ बड़ौदा
american express: अमेरिकन एक्सप्रेस |
standard chartered: स्टैंडर्ड चार्टर्ड |
railway station: रेलवे स्टेशन |
# --- answers to the bot's questions
bhej do: भेज दो | भेज दीजिए
karwa: करवा
"""

def _build() -> tuple[dict[str, str], dict[tuple[str, ...], str]]:
    words: dict[str, str] = {}
    phrases: dict[tuple[str, ...], str] = {}
    for raw in _TABLE.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        roman, _, spellings = line.partition(":")
        roman = roman.strip()
        if "|" in spellings:
            for sp in spellings.split("|"):
                toks = tuple(canon(t) for t in sp.split())
                if len(toks) > 1:
                    phrases.setdefault(toks, roman)
                elif toks:
                    words.setdefault(toks[0], roman)
            continue
        for sp in spellings.split():
            words.setdefault(canon(sp), roman)
    return words, phrases


LEXICON, PHRASES = _build()
MAX_PHRASE = max(len(k) for k in PHRASES)


def lookup(word: str) -> str | None:
    return LEXICON.get(canon(word))

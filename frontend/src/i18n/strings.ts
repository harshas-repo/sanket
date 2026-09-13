/**
 * Interface strings, English and Nepali.
 *
 * Scope rule, and it is the reason this file is small: the backend already writes the
 * *content* in the reader's language - `status_label`, `next_step`, `empty_message`, an
 * assistant reply, a quoted bulletin. None of that goes through `t()`. Only the chrome this
 * app adds (headings, buttons, field labels, the words on a chip) is translated here, so a
 * Nepali reader never sees a screen that is half one language and half the other.
 *
 * The enum labels below match the values the backend sends exactly; a label that is
 * missing falls back to the raw value rather than to nothing, because an untranslated
 * `district_centroid` on screen is better than a blank.
 */

export type Language = "en" | "ne";

export const LANGUAGES: { value: Language; label: string }[] = [
  { value: "en", label: "English" },
  { value: "ne", label: "नेपाली" },
];

export const STRINGS = {
  /* product */
  app_name: { en: "SANKET", ne: "सङ्केत" },
  app_tagline: {
    en: "Disaster intelligence and a two-way line to the people it serves",
    ne: "प्रकोप सूचना र जनतासँग दुई·तर्फे सञ्चार",
  },
  surface_rc: { en: "Response Center", ne: "प्रतिक्रिया केन्द्र" },
  surface_community: { en: "Community", ne: "समुदाय" },

  /* navigation */
  nav_overview: { en: "Overview", ne: "सारांश" },
  nav_queue: { en: "Action queue", ne: "कार्य सूची" },
  nav_incidents: { en: "Incidents", ne: "घटनाहरू" },
  nav_reports: { en: "Community reports", ne: "समुदायका खबर" },
  nav_requests: { en: "Help requests", ne: "सहयोग अनुरोध" },
  nav_resources: { en: "Facilities", ne: "स्रोत साधन" },
  nav_sources: { en: "Data sources", ne: "डाटा स्रोत" },
  nav_activity: { en: "Activity", ne: "गतिविधि" },
  nav_audit: { en: "Audit log", ne: "अडिट लग" },
  nav_assistant: { en: "Assistant", ne: "सहायक" },
  nav_feed: { en: "Near me", ne: "मेरो वरिपरि" },
  nav_report: { en: "Report", ne: "खबर पठाउनुहोस्" },
  nav_help: { en: "Ask for help", ne: "सहयोग माग्नुहोस्" },
  nav_mine: { en: "My requests", ne: "मेरा अनुरोध" },
  nav_account: { en: "Account", ne: "खाता" },
  sign_out: { en: "Sign out", ne: "लगआउट" },
  sign_in: { en: "Sign in", ne: "लगइन" },

  /* auth */
  username: { en: "Username", ne: "प्रयोगकर्ता नाम" },
  password: { en: "Password", ne: "गोप्य शब्द" },
  demo_accounts: { en: "Demo accounts", ne: "नमुना खाता" },
  signing_in: { en: "Signing in…", ne: "लगइन हुँदैछ…" },
  login_failed: { en: "Could not sign in", ne: "लगइन हुन सकेन" },
  use_account: { en: "Use", ne: "प्रयोग" },
  signed_in_as: { en: "Signed in as {name}", ne: "{name} को रूपमा लगइन भएको" },
  not_built: {
    en: "This screen is not built yet.",
    ne: "यो स्क्रीन अझै बनेको छैन।",
  },

  /* states - these three are never mixed up with each other on screen */
  loading: { en: "Loading", ne: "लोड हुँदैछ" },
  empty_title: { en: "Nothing here", ne: "यहाँ केही छैन" },
  error_title: { en: "This did not load", ne: "यो खोल्न सकिएन" },
  retry: { en: "Try again", ne: "फेरि प्रयास गर्नुहोस्" },
  offline_banner: {
    en: "You are offline. Anything you send is queued on this phone and goes when signal returns.",
    ne: "इन्टरनेट छैन। पठाएको कुरा फोनमा राखिन्छ र नेटवर्क आउँदा जान्छ।",
  },
  unreachable: {
    en: "The server is not answering. What is on screen may be older than it looks.",
    ne: "सर्भर जवाफ दिँदैन। स्क्रीनमा देखिएको डाटा पुरानो हुन सक्छ।",
  },
  stale_warning: {
    en: "Showing the last data that loaded, which may be out of date: {detail}",
    ne: "पछिल्लो पटक खुलेको डाटा देखाइरहेको छ, यो पुरानो हुन सक्छ: {detail}",
  },

  /* provenance */
  demo_warning: {
    en: "Rehearsal rows are marked. They are never merged with real records.",
    ne: "नमुना रेकर्ड चिन्ह लगाइएका छन्। ती वास्तविक डाटासँग कहिल्यै मिल्दैनन्।",
  },
  generated_at: { en: "Generated", ne: "बनाइएको" },
  provenance_official: { en: "Official", ne: "आधिकारिक" },
  provenance_community: { en: "Community", ne: "समुदाय" },
  provenance_derived: { en: "Computed", ne: "हिसाब गरिएको" },
  provenance_operator: { en: "Staff entry", ne: "कर्मचारीले भरेको" },
  provenance_open_data: { en: "Open data", ne: "खुला डाटा" },
  provenance_demo: { en: "Rehearsal", ne: "नमुना" },

  /* urgency */
  urgency_critical: { en: "Critical", ne: "अति गम्भीर" },
  urgency_urgent: { en: "Urgent", ne: "तत्काल" },
  urgency_attention: { en: "Needs attention", ne: "ध्यान दिनुपर्ने" },
  urgency_information: { en: "Information", ne: "सूचना" },

  /* evidence - what is known, not how bad it is */
  evidence_officially_confirmed: {
    en: "Officially confirmed",
    ne: "आधिकारिक रूपमा पुष्टि",
  },
  evidence_officially_reported: { en: "Officially reported", ne: "आधिकारिक रिपोर्ट" },
  evidence_corroborated: { en: "Corroborated", ne: "दुई स्रोतले मिलेर" },
  evidence_community_reported: { en: "Community reported", ne: "समुदायले खबर" },
  evidence_conflicting: { en: "Conflicting", ne: "विरोधाभास" },
  evidence_unverified: { en: "Unverified", ne: "अपुष्ट" },

  /* freshness */
  freshness_fresh: { en: "Fresh", ne: "ताजा" },
  freshness_recent: { en: "Recent", ne: "भरै" },
  freshness_aging: { en: "Aging", ne: "पुरानो हुँदै" },
  freshness_stale: { en: "Stale", ne: "पुरानो" },
  freshness_unknown: { en: "Age unknown", ne: "उमेर थाहा छैन" },

  /* how precisely a location is known */
  precision_source_coordinate: { en: "Source coordinate", ne: "स्रोतको निर्देशांक" },
  precision_named_place: { en: "Named place", ne: "नामिएको ठाउँ" },
  precision_local_level: { en: "Local level", ne: "स्थानीय तह" },
  precision_district_centroid: { en: "District centre", ne: "जिल्ला केन्द्र" },
  precision_user_shared: { en: "Shared by reporter", ne: "खबरकर्ताले बाँडेको" },
  precision_unlocated: { en: "No location", ne: "स्थान छैन" },

  /* How sure we are that a sender's own place is where they said it is. Not the map's precision
     list: `resolve_location()` reports confidence in these terms, and a rescue request has to say
     "we inferred this from your profile" out loud rather than show a code. */
  loc_conf_high: { en: "Location confirmed", ne: "स्थान पुष्टि भयो" },
  loc_conf_medium: { en: "Location likely", ne: "स्थान सम्भवतः सही" },
  loc_conf_low: { en: "Location uncertain", ne: "स्थान अनिश्चित" },
  loc_conf_text_only: { en: "Description only, not mapped", ne: "केवल विवरण, नक्सामा छैन" },
  loc_conf_inferred_home_district: {
    en: "Inferred from your home district",
    ne: "तपाईंको गृह जिल्लाबाट अनुमान गरियो",
  },
  loc_conf_inferred_home_district_staff: {
    en: "Inferred from the reporter's home district",
    ne: "खबर पठाउने व्यक्तिको गृह जिल्लाबाट अनुमान गरियो",
  },
  loc_conf_unknown: { en: "Location unknown", ne: "स्थान थाहा छैन" },

  /* What the console calls the same fact the community form asks as "Where are you?" - a
     question put to a resident is a strange heading on a screen an operator reads. */
  location_confidence: { en: "Location confidence", ne: "स्थानको विश्वसनीयता" },
  /* The column naming what a failed fetch reported - an ingestion run's own `error` text, on the
     sources screen. `error_title` ("This did not load") is a heading for a reader facing a broken
     screen, not a name for a column of stored error text, which is where it had been reused twice. */
  col_error: { en: "Error", ne: "त्रुटि" },

  /* hazard types */
  type_flood: { en: "Flood", ne: "बाढी" },
  type_landslide: { en: "Landslide", ne: "पहिरो" },
  type_earthquake: { en: "Earthquake", ne: "भूकम्प" },
  type_heavy_rainfall: { en: "Heavy rainfall", ne: "भारी वर्षा" },
  type_storm: { en: "Storm", ne: "आँधी" },
  type_lightning: { en: "Lightning", ne: "बिजुली" },
  type_fire: { en: "Fire", ne: "आगलागी" },
  type_other: { en: "Other", ne: "अन्य" },

  /* shared fields */
  district: { en: "District", ne: "जिल्ला" },
  province: { en: "Province", ne: "प्रदेश" },
  location: { en: "Location", ne: "स्थान" },
  share_location: { en: "Share my location", ne: "मेरो स्थान बाँड्नुहोस्" },
  impact_score: { en: "Impact score", ne: "प्रभाव अंक" },
  why_prioritized: { en: "Why this is here", ne: "यो किन अगाडि छ" },
  people: { en: "People", ne: "जनसंख्या" },
  deaths: { en: "Deaths", ne: "मृत्यु" },
  injured: { en: "Injured", ne: "घाइते" },
  missing: { en: "Missing", ne: "वेपत्ता" },
  updated: { en: "Updated", ne: "अद्यावधिक" },
  source: { en: "Source", ne: "स्रोत" },
  status: { en: "Status", ne: "स्थिति" },
  search: { en: "Search", ne: "खोज्नुहोस्" },
  filters: { en: "Filters", ne: "छान्ने कुरा" },
  details: { en: "Details", ne: "विवरण" },
  close: { en: "Close", ne: "बन्द" },
  cancel: { en: "Cancel", ne: "रद्द" },
  save: { en: "Save", ne: "सुरक्षित" },
  submit: { en: "Submit", ne: "पठाउनुहोस्" },
  sending: { en: "Sending…", ne: "पठाउँदै…" },
  sent: { en: "Sent", ne: "पठायो" },
  optional: { en: "optional", ne: "ऐच्छिक" },
  required: { en: "This field is needed", ne: "यो कुरा आवश्यक छ" },
  too_long: { en: "That is too long for one message", ne: "यो सन्देश धेरै लामो छ" },

  /* community flow */
  feed_title: { en: "What is happening near you", ne: "तपाईंनजिक के भइरहेको छ" },
  report_prompt: {
    en: "Saw something? Describe it in your own words.",
    ne: "केही देख्नुभयो? आफ्नै शब्दमा लेख्नुहोस्।",
  },
  help_prompt: {
    en: "What do you need, and how many people?",
    ne: "के चाहिन्छ, कति जनालाई?",
  },
  voice_input: { en: "Speak", ne: "बोल्नुहोस्" },
  voice_stop: { en: "Stop", ne: "रोक्नुहोस्" },
  voice_unsupported: {
    en: "This browser cannot take voice input. Type it instead.",
    ne: "यो ब्राउजरले आवाज लिन सक्दैन। टाइप गर्नुहोस्।",
  },
  queued_offline: {
    en: "Saved on this phone. It will send when you get signal.",
    ne: "फोनमा राखियो। नेटवर्क आउँदा पठाइनेछ।",
  },
  what_happens_next: { en: "What happens next", ne: "अब के हुन्छ" },
  ref_code_hint: {
    en: "Keep this code to ask about your request",
    ne: "अनुरोधबारे सोध्न यो कोड राख्नुहोस्",
  },
  home_prompt: { en: "How can SANKET help?", ne: "संकेटले कसरी मद्दत गर्न सक्छ?" },
  ask_sanket: { en: "Ask SANKET", ne: "संकेटसँग सोध्नुहोस्" },
  ask_hint: { en: "What is happening in my area", ne: "मेरो क्षेत्रमा के भइरहेको छ" },
  report_hint: { en: "Tell us what you saw", ne: "तपाईंले देखेको कुरा बताउनुहोस्" },
  help_hint: { en: "Ask for rescue, treatment, food or shelter", ne: "उद्धार, उपचार, खाना वा आश्रय माग्नुहोस्" },
  alerts_hint: { en: "Official warnings for your area", ne: "तपाईंको क्षेत्रका आधिकारिक चेतावनी" },
  local_alerts: { en: "Local alerts", ne: "स्थानीय चेतावनी" },
  messages_for_you: { en: "Messages for you", ne: "तपाईंका सन्देश" },
  mark_read: { en: "Mark as read", ne: "पढिएको भनी चिन्ह" },
  send_offline: {
    en: "Save it and send when signal returns",
    ne: "राख्नुहोस्, नेटवर्क आउँदा पठाइनेछ",
  },
  queued_count: { en: "{count} waiting on this phone", ne: "{count} सन्देश यो फोनमा पर्खिरहेको" },
  flush_now: { en: "Try sending the saved ones again", ne: "राखेका फेरि पठाउन हेर्नुहोस्" },
  flush_sent: { en: "{count} saved messages went through", ne: "{count} राखेका सन्देश पठाइए" },
  pending_label: { en: "Waiting to send", ne: "पठाउन बाँकी" },
  remove_item: { en: "Remove from this phone", ne: "यो फोनबाट हटाउनुहोस्" },
  outbox_none: { en: "Nothing waiting on this phone", ne: "यो फोनमा केही बाँकी छैन" },
  offline_disabled: {
    en: "This browser will not store anything on the phone, so a message cannot be saved offline here.",
    ne: "यो ब्राउजरले फोनमा केही राख्दैन, त्यसैले यहाँ सन्देश अफलाइन राख्न मिल्दैन।",
  },
  loc_prompt: { en: "Where are you?", ne: "तपाईं कहाँ हुनुहुन्छ?" },
  loc_use: { en: "Use my location", ne: "मेरो स्थान प्रयोग गर्नुहोस्" },
  loc_locating: { en: "Finding your location…", ne: "तपाईंको स्थान खोज्दै…" },
  loc_denied: {
    en: "Location sharing was not allowed. Write where you are instead.",
    ne: "स्थान बाँड्न अनुमति छैन। कहाँ हुनुहुन्छ लेख्नुहोस्।",
  },
  loc_unavailable: {
    en: "This browser will not give a location over this connection.",
    ne: "यो जडानमा ब्राउजरले स्थान दिँदैन।",
  },
  loc_accuracy: { en: "about {metres} m wide", ne: "करिब {metres} मिटर फराकिलो" },
  loc_text_placeholder: {
    en: "Tole, ward, or a place everyone knows",
    ne: "टोल, वडा, वा सबैलाई थाहा भएको ठाउँ",
  },
  loc_none_note: {
    en: "With no location this can only be filed at district level.",
    ne: "स्थान नखुले यो जिल्लास्तरमा मात्र राखिन्छ।",
  },
  voice_hint: { en: "Tap and speak", ne: "थिच्नुहोस् र बोल्नुहोस्" },
  voice_network: {
    en: "Most phones put dictation through the internet, so it can fail with no signal. Typing always works.",
    ne: "धेरैजसो फोनमा आवाज इन्टरनेटमार्फत जान्छ, त्यसैले नेटवर्क नभई असफल हुनसक्छ। टाइप गर्दा सधैँ मिल्छ।",
  },
  voice_denied: {
    en: "The microphone was not allowed. Write it instead.",
    ne: "माइक्रोफोनलाई अनुमति छैन। टाइप गर्नुहोस्।",
  },
  char_count: { en: "{n} of {max} characters", ne: "{max} मध्ये {n} अक्षर" },
  ask_placeholder: { en: "Ask about your area", ne: "तपाईंको क्षेत्रबारे सोध्नुहोस्" },
  ask_offline: {
    en: "Asking needs a connection. A report or a request for help can be saved on this phone instead.",
    ne: "सोध्न इन्टरनेट चाहिन्छ। खबर वा सहयोग अनुरोध भने यो फोनमा राख्न मिल्छ।",
  },
  ask_intro: {
    en: "SANKET answers from the same official records your screen shows, and says what it does not know.",
    ne: "संकेटले तपाईंको स्क्रिनमा देखाएको आधिकारिक अभिलेखबाटै जवाफ दिन्छ, र थाहा नभएको कुरा स्पष्ट पार्छ।",
  },
  answer_rules: {
    en: "Written by SANKET's own rules from the records, not by a language model",
    ne: "अभिलेखबाट संकेटकै नियमले लेखिएको, भाषा मोडेलबाट होइन",
  },
  answer_model: {
    en: "Wording produced by a language model from the records listed below",
    ne: "तल सूचीकृत अभिलेखबाट भाषा मोडेलले लेखएको शब्द",
  },
  based_on: { en: "What it is based on", ne: "के आधारमा" },
  not_known: { en: "What it does not know", ne: "के थाहा छैन" },
  my_reports: { en: "My reports", ne: "मेरा रिपोर्ट" },
  nothing_yet: {
    en: "Nothing has been sent from this account yet",
    ne: "यस खाताबाट अहिलेसम्म केही पठाइएको छैन",
  },
  cancel_request: { en: "Cancel this request", ne: "यो अनुरोध रद्द गर्नुहोस्" },
  cancel_help: {
    en: "Say why, so a team is not sent to the wrong place",
    ne: "किन भन्नुहोस्, टोली गल्ती ठाउँमा नजाओस्",
  },
  receipt_title: { en: "Your reference", ne: "तपाईंको सन्दर्भ कोड" },
  help_types_note: { en: "Pick up to {max}", ne: "{max} सम्म छान्नुहोस्" },
  danger_note: {
    en: "If someone is in danger right now, also call the emergency services. This form is not faster than a phone call.",
    ne: "अहिले नै जोखिममा कोही छ भने आपतकालीन सेवालाई पनि फोन गर्नुहोस्। यो फारम फोनभन्दा छिटो होइन।",
  },
  public_official_note: {
    en: "Only the official record is shown here. The reports below are what people said, not an official confirmation.",
    ne: "यहाँ आधिकारिक अभिलेख मात्र देखाइएको छ। तलका रिपोर्ट जनताका भनाइ हुन्, आधिकारिक पुष्टि होइन।",
  },
  home_district: { en: "Home district", ne: "आफ्नो जिल्ला" },
  pref_language_note: {
    en: "This is the language SANKET writes its own messages in - alerts, answers and case updates. The switch in the header changes only what is on this screen.",
    ne: "यो संकेटले आफ्ना सन्देश (चेतावनी, जवाफ, अनुरोधको अपडेट) लेख्ने भाषा हो। हेडरको बटनले यो स्क्रीन मात्र फेर्छ।",
  },
  district_note: {
    en: "The name is matched against the official district list. Spelled differently, the feed for this area simply comes up empty.",
    ne: "यो नाम आधिकारिक जिल्ला सूचीसँग मिलाइन्छ। फरक तरिकाले लेखे यस क्षेत्रको सूची खाली आउँछ।",
  },
  profile_saved: { en: "Saved", ne: "सुरक्षित गरियो" },
  account_intro: {
    en: "What the platform assumes about you, and what you can change",
    ne: "मञ्चले तपाईंबारे के मान्छ र के फेर्न सकिन्छ",
  },
  alert_undated: {
    en: "This bulletin carries no date of its own",
    ne: "यस सूचनामा आफ्नै मिति छैन",
  },
  alert_pdf: {
    en: "The original is a PDF bulletin, so this text may be incomplete",
    ne: "मूल PDF सूचना हो, त्यसैले यो पाठ अपूरो हुनसक्छ",
  },
  signal_prediction: {
    en: "A forecast, not something observed",
    ne: "यो अनुमान हो, अवलोकन होइन",
  },
  signal_observed: {
    en: "Raised from records that were observed",
    ne: "देखिएका अभिलेखबाट उठेको",
  },
  hazard_inferred_note: {
    en: "Leave this alone and SANKET reads the kind from your words",
    ne: "यो छोड्नुहोस्, संकेटले तपाईंका शब्दबाट प्रकार बुझ्छ",
  },
  help_cta: { en: "I need help now", ne: "मलाई अहिले सहयोग चाहिएको छ" },
  help_switch_note: {
    en: "Left off, this message is filed as information for the Response Center. Switched on, it also opens a help request someone must answer.",
    ne: "नखोले यो सन्देश प्रतिक्रिया केन्द्रलाई सूचनाका रूपमा राखिन्छ। खोले त्यससँगै कसैले जवाफ दिनुपर्ने सहयोग अनुरोध पनि खुल्छ।",
  },

  privacy_note: {
    en: "Only your own cases appear here. Another person's request, and who is going to them, is never shown to you.",
    ne: "यहाँ तपाईंका आफ्नै अनुरोध मात्र देखाइन्छ। अर्को व्यक्तिको अनुरोध र कसलाई पठाइएको छ, तपाईंलाई कहिल्यै देखाइँदैन।",
  },
  case_closed_note: {
    en: "This case is closed. Nothing further will be sent unless you ask again.",
    ne: "यो अनुरोध टुग्रेको छ। फेरि नमात्तम्म थप केही पठाइने छैन।",
  },

  /* the taxonomies a resident picks from, and the state a report reaches */
  type_road_blockage: { en: "Road blockage", ne: "सडक अवरोध" },
  type_infrastructure_damage: { en: "Infrastructure damage", ne: "पूर्वाधार क्षति" },
  assist_medical: { en: "Medical", ne: "उपचार" },
  assist_rescue: { en: "Rescue", ne: "उद्धार" },
  assist_food: { en: "Food", ne: "खाना" },
  assist_water: { en: "Water", ne: "पानी" },
  assist_shelter: { en: "Shelter", ne: "आश्रय" },
  assist_transport: { en: "Transport", ne: "यातायात" },
  assist_information: { en: "Information", ne: "सूचना" },
  assist_other: { en: "Other", ne: "अन्य" },
  rtype_incident: { en: "An incident", ne: "घटना" },
  rtype_condition: { en: "A condition", ne: "अवस्था" },
  rtype_damage: { en: "Damage", ne: "क्षति" },
  rtype_sought_person: { en: "Looking for a person", ne: "व्यक्ति खोजी" },
  rtype_offered_help: { en: "An offer of help", ne: "सहयोगको प्रस्ताव" },
  verify_pending: { en: "Waiting for an operator", ne: "सञ्चालक पर्खिरहेको" },
  verify_verified: { en: "Verified by an operator", ne: "सञ्चालकले प्रमाणित" },
  verify_rejected: { en: "Not used by an operator", ne: "सञ्चालकले प्रयोग गरेनन्" },
  verify_duplicate: { en: "Same as another report", ne: "अर्को रिपोर्टसँग उही" },
  verify_conflicting: { en: "Contradicts another report", ne: "अर्को रिपोर्टसँग विरोध" },

  /* response centre */
  queue_title: { en: "Action queue", ne: "कार्य सूची" },
  sla_breaches: { en: "Past their response deadline", ne: "समय नाघेका" },
  unacknowledged_critical: { en: "Critical, not yet acknowledged", ne: "गम्भीर, अझै हेरिएका छैनन्" },
  open_requests: { en: "Open requests", ne: "खुला अनुरोध" },
  needs_review: { en: "Needs review", ne: "पुनरावलोकन आवश्यक" },
  take_action: { en: "Take action", ne: "कार्य गर्नुहोस्" },
  no_actions: {
    en: "Your role cannot act on this record.",
    ne: "तपाईंको भूमिकाले यसमा कार्य गर्न सक्दैन।",
  },
  evidence_behind: { en: "What this is based on", ne: "यो कुन डाटाबाट बन्यो" },
  agent_unavailable: {
    en: "No language model is configured. The deterministic answers below come from retrieved records only.",
    ne: "कुनै भाषा मोडल छैन। तलका जवाफ संग्रहीत रेकर्डबाट मात्र बनेका छन्।",
  },
  ask_agent: { en: "Ask about this situation", ne: "य अवस्थाबारे सोध्नुहोस्" },

  /* overview */
  overview_intro: {
    en: "Every number here was computed from the records named on the Data sources page. Nothing on this screen is estimated by a language model.",
    ne: "यहाँका सबै अङ्क डाटा स्रोत पृष्ठमा उल्लिखित रेकर्डबाट हिसाब गरिएका हुन्। यो स्क्रीनमा कुनै कुरा भाषा मोडलले अनुमान गरेको होइन।",
  },
  active_incidents: { en: "Active incidents", ne: "सक्रिय घटनाहरू" },
  new_24h: { en: "New in 24 hours", ne: "२४ घण्टामा नयाँ" },
  cross_validated: { en: "Confirmed by two or more sources", ne: "दुई वा बढी स्रोतले पुष्टि गरेका" },
  critical_open: { en: "Critical and still open", ne: "गम्भीर र अझै खुला" },
  reports_24h: { en: "Community reports in 24 hours", ne: "२४ घण्टाका समुदाय खबर" },
  pending_verification: { en: "Reports waiting for a staff check", ne: "जाँच पर्खिरहेका खबर" },
  by_type: { en: "Active incidents by event type", ne: "प्रकार अनुसार सक्रिय घटना" },
  last_change: { en: "Last change", ne: "पछिल्लो परिवर्तन" },
  open_queue: { en: "Open the action queue", ne: "कार्य सूची खोल्नुहोस्" },
  queue_is_empty: {
    en: "Nothing is waiting for an action right now.",
    ne: "अहिले कुनै कार्य पर्खिरहेको छैन।",
  },

  /* action queue */
  queue_intro: {
    en: "Ordered by the published scoring formula and response deadlines, not by who reported last.",
    ne: "कार्य सूची प्रकाशित सूत्र र समयसीमा अनुसार मिलाइएको हो, अन्तिममा कसले खबर गर्यो त्यसै अनुसार होइन।",
  },
  queue_total: { en: "{count} items need someone", ne: "{count} कुरामा कसैको आवश्यकता" },
  why_in_queue: { en: "Why this is here", ne: "यो यहाँ किन छ" },
  age: { en: "Age", ne: "अवधि" },
  refresh: { en: "Refresh", ne: "ताजा गर्नुहोस्" },
  auto_refresh: { en: "Refreshes every {seconds} s", ne: "{seconds} सेकेन्डमा आफैँ ताजा हुन्छ" },
  /* The Overview screen's own line, worded as what is happening rather than as a clock it keeps:
     it asks the official feeds on opening and on Refresh, so it has no interval to advertise. */
  refreshing_official: {
    en: "Asking the official feeds for anything new…",
    ne: "आधिकारिक स्रोतबाट नयाँ डाटा ल्याउँदै…",
  },
  /* The button's own short version of the line above - the sentence belongs on the note, not on a
     control that has to fit the same width while it changes. */
  refreshing: { en: "Refreshing…", ne: "ताजा गर्दै…" },
  cached_note: {
    en: "Showing what this screen held from your last visit, while the newest data arrives",
    ne: "यो स्क्रिनमा अघिल्लो पटकको डाटा देखाइरहेको छ, नयाँ डाटा आउँदैछ",
  },
  poll_not_started: {
    en: "The server did not start a fetch; these are the figures it already holds",
    ne: "सर्भरले नयाँ डाटा ल्याउन सुरु गरेन; योसँग पहिले नै रहेको डाटा देखाइएको छ",
  },
  bucket_empty: { en: "Nothing at this level", ne: "यस तहमा केही छैन" },
  open_record: { en: "Open", ne: "खोल्नुहोस्" },
  queue_kind_assistance_request: { en: "Help request", ne: "सहयोग अनुरोध" },
  queue_kind_incident_review: { en: "Incident to review", ne: "हेर्नुपर्ने घटना" },

  /* incident list */
  incidents_intro: {
    en: "One record per event. Reports from many people about the same event are merged into it, and the merge is visible on the record.",
    ne: "एक घटनाको एक रेकर्ड। एउटै घटनाका धेरै खबर एकैमा जोडिन्छन् र जोडिएको कुरा रेकर्डमा देखिन्छ।",
  },
  filter_all: { en: "All", ne: "सबै" },
  filter_urgency: { en: "Urgency", ne: "तत्कालता" },
  filter_evidence: { en: "Evidence", ne: "प्रमाण" },
  show_archived: { en: "Include archived incidents", ne: "संग्रहित घटना पनि" },
  unassigned_only: { en: "Only those no one has taken", ne: "कसैले नलिएका मात्र" },
  filter_type: { en: "Event type", ne: "घटनाको प्रकार" },
  filter_district: { en: "District", ne: "जिल्ला" },
  clear_filters: { en: "Clear filters", ne: "छानाइ हटाउनुहोस्" },
  showing_of: { en: "Showing {shown} of {total}", ne: "{total} मध्ये {shown} देखाइरहेको" },
  no_incidents_match: {
    en: "No incident matches these filters. That is a fact about the filters, not proof that nothing is happening.",
    ne: "यी छानाइमेल्ट कुनै घटना छैन। यो छानिको कुरा हो, केही भइरहेको छैन भन्ने प्रमाण होइन।",
  },
  event_time: { en: "Event time", ne: "घटनाको समय" },
  score_band: { en: "Score band", ne: "अंक श्रेणी" },
  col_incident: { en: "Incident", ne: "घटना" },
  col_district: { en: "District", ne: "जिल्ला" },
  col_urgency: { en: "Urgency", ne: "तत्काल" },
  col_status: { en: "Status", ne: "स्थिति" },
  col_score: { en: "Impact", ne: "प्रभाव" },
  col_reports: { en: "Reports", ne: "खबर" },
  col_requests: { en: "Requests", ne: "अनुरोध" },
  col_count: { en: "Count", ne: "संख्या" },
  col_time: { en: "When", ne: "समय" },
  col_type: { en: "Type", ne: "प्रकार" },
  total: { en: "Total", ne: "जम्मा" },
  ref_code: { en: "Reference", ne: "सन्दर्भ नम्बर" },
  description: { en: "What was said", ne: "के भनियो" },
  request_type: { en: "Request type", ne: "अनुरोधको प्रकार" },
  help_types: { en: "Help asked for", ne: "कुन सहयोग मागिएको" },
  attached_none: {
    en: "Nothing is attached to this record.",
    ne: "यस रेकर्डमा केही जोडिएको छैन।",
  },
  contact: { en: "Contact", ne: "सम्पर्क" },
  context_flags: { en: "What the caller said", ne: "सोध्नेले भनेको" },
  queue_show_information: {
    en: "Also list the informational items",
    ne: "सूचनात्मक कुरा पनि सूचीमा राख्नुहोस्",
  },

  /* incident and request detail */
  back_to_incidents: { en: "All incidents", ne: "सबै घटना" },
  record_not_found: {
    en: "This record is not there, or your role is not allowed to see it.",
    ne: "यो रेकर्ड छैन, वा तपाईंको भूमिकाले हेर्न पाउँदैन।",
  },
  score_components: { en: "Score components", ne: "अंकका घटक" },
  col_raw: { en: "Raw", ne: "मान" },
  col_weight: { en: "Weight", ne: "तौल" },
  col_contribution: { en: "Contribution", ne: "योगदान" },
  formula: { en: "Formula", ne: "सूत्र" },
  freshness_multiplier: { en: "Freshness multiplier", ne: "ताजापन गुणक" },
  source_records: { en: "{count} source records", ne: "{count} स्रोत रेकर्ड" },
  no_source_records: {
    en: "No source record is attached to this incident. It cannot be called confirmed.",
    ne: "यस घटनासँग कुनै स्रोत रेकर्ड जोडिएको छैन। यसलाई पुष्टि भनिरहन मिल्दैन।",
  },
  confirmed_by: { en: "Confirmed by", ne: "पुष्टि गर्ने" },
  verified_by_operator: { en: "Verified by an operator", ne: "कर्मचारीले प्रमाणित गरे" },
  conflicting_records: { en: "Conflicting records", ne: "विरोधाभासी रेकर्ड" },
  col_role: { en: "Role", ne: "भूमिका" },
  col_authority: { en: "Authority", ne: "प्राधिकार" },
  open_source_record: { en: "Open the source", ne: "स्रोत खोल्नुहोस्" },
  linked_at: { en: "Linked", ne: "जोडिएको" },
  timeline_title: { en: "Timeline", ne: "समयरेखा" },
  no_timeline: { en: "Nothing has happened to this record since it was created.", ne: "बनेपछि यसमा केही भएको छैन।" },
  attached_reports: { en: "Community reports on this incident", ne: "यस घटनाका समुदाय खबर" },
  attached_requests: { en: "Help requests on this incident", ne: "यस घटनाका सहयोग अनुरोध" },
  attached_signals: { en: "Risk signals nearby", ne: "नजिकका जोखिम संकेत" },
  attached_alerts: { en: "Official alerts on this incident", ne: "यस घटनाका आधिकारिक चेतावनी" },
  duplicates_merged: { en: "Duplicates carried into this record", ne: "यसमा जोडिएका दोहोरिएका रेकर्ड" },
  related_incidents: { en: "Related incidents", ne: "सम्बन्धित घटनाहरू" },
  changes_to_record: { en: "Changes to this record", ne: "यस रेकर्डमा परिवर्तन" },
  col_action: { en: "Action", ne: "कार्य" },
  col_actor: { en: "Who", ne: "कसले" },
  before: { en: "Before", ne: "अघि" },
  after: { en: "After", ne: "पछि" },
  reason: { en: "Reason", ne: "कारण" },
  houses_damaged: { en: "Houses damaged", ne: "क्षतिग्रस्त घर" },
  displaced_persons: { en: "Displaced people", ne: "विस्थापित" },
  review_flag: {
    en: "Flagged for a human: {reason}",
    ne: "मानिसले हेर्नुपर्ने: {reason}",
  },
  requester_language: { en: "Written in", ne: "कुन भाषामा लेखिएको" },
  immediate_danger: { en: "Immediate danger reported", ne: "तत्काल जोखिम भनिएको" },
  medical_need: { en: "Medical need reported", ne: "चिकित्सा आवश्यक भनिएको" },
  trapped: { en: "People trapped", ne: "फसेका मान्छे" },
  minors_involved: { en: "Minors involved", ne: "नाबालिग सम्मिलित" },
  elderly_or_disabled: { en: "Elderly or disabled people", ne: "बुढा वा अपाङ्ग व्यक्ति" },
  sla_due: { en: "Response due", ne: "जवाफ दिनुपर्ने समय" },
  acknowledged: { en: "Acknowledged", ne: "हेरेँ भनी दर्ता भयो" },
  /* `minutes` already carries its own unit (`40 min`, `5 h 27 min`) - see `utils/time.ts`. */
  sla_remaining: { en: "{minutes} left", ne: "अझै {minutes} बाँकी" },
  sla_overdue: { en: "Overdue by {minutes}", ne: "{minutes} ढिलो" },
  sla_no_deadline: { en: "No deadline was set for this request", ne: "यस अनुरोधको समयसीमा तोकिएको छैन" },
  planned_response: { en: "Planned response", ne: "योजना बनाइएको जवाफ" },
  plan_unknowns: { en: "Still not known", ne: "अझै थाहा नभएको" },
  plan_generated_by: { en: "Produced by", ne: "कसले बनायो" },
  victim_view: { en: "What the person who asked can see", ne: "सोध्ने व्यक्तिले के देख्न सक्छ" },
  victim_view_of_plan: { en: "Shown to the requester", ne: "सोध्नेलाई देखिने" },
  matched_facilities: { en: "Facilities named by dispatch", ne: "पठाउनेले नाम दिएका स्थल" },
  distance: { en: "Distance", ne: "दूरी" },
  assigned_to: { en: "Assigned to", ne: "कोलाई तोलियो" },

  /* actions */
  actions_title: { en: "Actions", ne: "कार्य" },
  actions_hint: {
    en: "These buttons are the list the server said you may use on this record. Nothing is offered here that the API would refuse.",
    ne: "यी बटन सर्भरले तपाईंलाई दिन अनुमति दिएको सूची हो। जवाफ नदिने कुनै बटन यहाँ राखिएको छैन।",
  },
  no_actions_for_role: { en: "The server offered you no action on this record.", ne: "सर्भरले यसमा कुनै कार्य सुझाएन।" },
  run_action: { en: "Do it", ne: "कार्य गर्नुहोस्" },
  action_done: { en: "Done - the record was reloaded.", ne: "भयो - रेकर्ड फेरि लोडियो।" },
  action_failed: { en: "That action did not go through.", ne: "यो कार्य भएन।" },
  action_no_form: {
    en: "This action has no form on this screen yet, so it is not offered.",
    ne: "यस कार्यको फारम अझै यो स्क्रीनमा छैन, त्यसैले सुझाइएको छैन।",
  },
  action_reason_hint: { en: "Why - written into the audit log", ne: "किन - अडिट लगमा बस्छ" },
  action_note_hint: { en: "Your note", ne: "तपाईंको टिप्पणी" },
  action_target_hint: { en: "Id of the record to attach", ne: "जोड्नुपर्ने रेकर्डको आईडी" },
  action_message_hint: { en: "Message for the person who asked", ne: "सोध्ने व्यक्ति पठाउने सन्देश" },
  action_required: { en: "This action needs a reason before it can be sent.", ne: "पठाउनुअघि कारण चाहिन्छ।" },
  ra_acknowledge: { en: "Acknowledge", ne: "हेरेँ भनी दर्ता" },
  ra_assign: { en: "Assign a team", ne: "टोली तोक्नुहोस्" },
  ra_escalate: { en: "Escalate", ne: "माथि पठाउनुहोस्" },
  ra_note: { en: "Add a note", ne: "टिप्पणी थप्नुहोस्" },
  ra_message: { en: "Message the requester", ne: "सोध्नेलाई सन्देश" },
  ra_cancel: { en: "Cancel this request", ne: "यो अनुरोध रद्द" },
  ra_status_to: { en: "Move to {status}", ne: "{status} मा लैजानुहोस्" },
  team_name: { en: "Team to send", ne: "पठाउने टोली" },

  status_received: { en: "Received", ne: "पाइयो" },
  status_reviewing: { en: "Being reviewed", ne: "हेरिरहेको" },
  status_response_team_notified: { en: "Team notified", ne: "टोलीलाई खबर गरियो" },
  status_assigned: { en: "Team assigned", ne: "टोली तोलियो" },
  status_in_progress: { en: "In progress", ne: "काम भइरहेको" },
  status_resolved: { en: "Resolved", ne: "समाधान भयो" },
  status_cancelled: { en: "Cancelled", ne: "रद्द भयो" },

  incident_status_active: { en: "Active", ne: "सक्रिय" },
  incident_status_monitoring: { en: "Monitoring", ne: "नजरमा" },
  incident_status_contained: { en: "Contained", ne: "नियन्त्रणमा" },
  incident_status_resolved: { en: "Resolved", ne: "समाधान भयो" },
  incident_status_archived: { en: "Archived", ne: "संग्रह" },

  /* chrome the shell adds */
  language: { en: "Language", ne: "भाषा" },
  back: { en: "Back", ne: "पछाडि" },
  menu: { en: "Sections", ne: "अन्य भागहरू" },

  /* reports, resources and the rest of the console */
  reports_intro: {
    en: "Every message a person sent, and whether an operator has checked it.",
    ne: "मान्छेले पठाएका हरेक सन्देश, र सञ्चालकले जाँचेको छ कि छैन।",
  },
  include_duplicates: { en: "Include duplicates", ne: "नक्कलहरू पनि देखाउनुहोस्" },
  verify_action: { en: "Record your verification", ne: "आफ्नो जाँच दर्ता गर्नुहोस्" },
  verify_reason_hint: {
    en: "Say what made you sure. This is written into the audit trail.",
    ne: "केले पक्का बनायो भन्नुहोस्। यो अडिट लगमा लेखिन्छ।",
  },
  verify_done: { en: "Verification recorded.", ne: "जाँच दर्ता भयो।" },
  linked_incident: { en: "Linked situation", ne: "जोडिएको घटना" },
  carried_on_request: { en: "Carried onto request", ne: "अनुरोधमा जोडिएको" },
  corroboration: { en: "Corroborating reports", ne: "समर्थन गर्ने खबरहरू" },
  resources_intro: {
    en: "Facilities a coordinator can send people to, with how sure we are that they are open.",
    ne: "समन्वयकर्ताले मान्छे पठाउन सक्ने सुविधाहरू, खुला छन् कि होइनन् भन्ने कति पक्का छ त्यो सहित।",
  },
  resource_catalogue: { en: "Catalogue", ne: "सूची" },
  by_availability: { en: "By availability", ne: "उपलब्धता अनुसार" },
  catalogue_empty_reason: { en: "Why this is empty", ne: "यो किन खाली छ" },
  add_resource: { en: "Add a facility", ne: "सुविधा थप्नुहोस्" },
  resource_name: { en: "Name", ne: "नाम" },
  resource_address: { en: "Address", ne: "ठेगाना" },
  update_availability: { en: "Update availability", ne: "उपलब्धता अद्यावधिक गर्नुहोस्" },
  deactivate_resource: { en: "Deactivate", ne: "निष्क्रिय पार्नुहोस्" },
  deactivate_hint: {
    en: "Say why, so the next shift knows it was a decision and not a mistake.",
    ne: "किन भन्नुहोस्, ताकि अर्को पालीले यो निर्णय हो, गल्ती होइन भनेर थाहा पाउन्।",
  },
  seed_state: { en: "Seeding", ne: "स्रोत भर्ने अवस्था" },
  seed_run: { en: "Seed from OpenStreetMap", ne: "OpenStreetMap बाट भर्नुहोस्" },
  seed_running: { en: "Seeding is running", ne: "भर्ने काम चलिरहेको छ" },
  seed_result: { en: "Result", ne: "नतिजा" },
  last_verified: { en: "Last checked", ne: "अन्तिम जाँच" },
  contact_unverified: { en: "Contact not verified", ne: "सम्पर्क जाँचिएको छैन" },
  not_on_map: { en: "Not on the map", ne: "नक्सामा छैन" },
  rt_hospital: { en: "Hospital", ne: "अस्पताल" },
  rt_health_post: { en: "Health post", ne: "स्वास्थ्य चौकी" },
  rt_ambulance: { en: "Ambulance", ne: "एम्बुलेन्स" },
  rt_shelter: { en: "Shelter", ne: "आश्रय स्थल" },
  rt_police: { en: "Police", ne: "प्रहरी" },
  rt_army: { en: "Army", ne: "सेना" },
  rt_fire: { en: "Fire service", ne: "दमकल" },
  rt_water_supply: { en: "Water supply", ne: "खानेपानी" },
  rt_food_distribution: { en: "Food distribution", ne: "खाद्यान्न वितरण" },
  rt_helipad: { en: "Helipad", ne: "हेलिप्याड" },
  rt_emergency_contact: { en: "Emergency contact", ne: "आपतकालीन सम्पर्क" },
  av_unknown: { en: "Unknown", ne: "थाहा छैन" },
  av_available: { en: "Available", ne: "उपलब्ध" },
  av_limited: { en: "Limited", ne: "सीमित" },
  av_closed: { en: "Closed", ne: "बन्द" },
  sources_intro: {
    en: "Where the facts on the map came from, and whether each feed is still working.",
    ne: "नक्सामा देखिएका तथ्य कहाँबाट आए, र हरेक फिड अझै चल्दैछ कि छैन।",
  },
  machine_readable: { en: "Machine readable", ne: "मेसिनले पढ्न मिल्ने" },
  official_source: { en: "Official agency", ne: "आधिकारिक निकाय" },
  last_successful_fetch: { en: "Last successful fetch", ne: "अन्तिम सफल प्राप्त" },
  consecutive_failures: { en: "Failures in a row", ne: "लगातार असफलता" },
  records_found: { en: "Found", ne: "भेटिएका" },
  records_new: { en: "New", ne: "नयाँ" },
  records_updated: { en: "Updated", ne: "अद्यावधिक" },
  run_source: { en: "Fetch now", ne: "अहिले लिनुहोस्" },
  run_due: { en: "Fetch everything due", ne: "समय भएका सबै लिनुहोस्" },
  ingestion_runs: { en: "Recent fetches", ne: "हालैका प्राप्त" },
  /* The one thing the table below cannot say: whether anything is polling at all. Every source can
     read `healthy` with a check from an hour ago because the worker stopped, and by table alone
     that is indistinguishable from a quiet upstream. `last_cycle_label` already carries "ago". */
  ingestion_worker: { en: "Ingestion worker", ne: "डाटा ल्याउने सेवा" },
  worker_running: { en: "Running", ne: "सञ्चालनमा छ" },
  worker_stopped: { en: "Not running", ne: "सञ्चालनमा छैन" },
  worker_unknown: { en: "Nothing to ask", ne: "सोध्न केही छैन" },
  worker_last_cycle: { en: "Last cycle {age}", ne: "अन्तिम चक्र {age}" },
  refresh_interval: { en: "Every {seconds}s", ne: "हरेक {seconds} सेकेन्ड" },
  col_interval: { en: "Interval", ne: "अन्तराल" },
  /* A `refresh_interval_seconds` of 0 is not "never" and not "now" - the worker's test is
     `elapsed >= 0`, which is true on every tick (`services/ingestion.py:283`), so the honest
     sentence is about the tick rather than about a number of seconds. */
  interval_every_tick: { en: "Every scheduler tick", ne: "सर्जुलरको हरेक चक्र" },
  /* `SourceStatus` (`shared/enums.py:131-136`) and the two values an ingestion run is ever set to
     (`services/ingestion.py:221,247`). The source page printed these raw on the theory that no
     vocabulary was published; the enum is the vocabulary, and `enumLabel` still echoes anything a
     later server adds that this list has not caught up with. */
  src_healthy: { en: "Healthy", ne: "राम्रो" },
  src_degraded: { en: "Degraded", ne: "कमजोर" },
  src_failing: { en: "Failing", ne: "असफल" },
  src_disabled: { en: "Disabled", ne: "निष्क्रिय" },
  src_never_fetched: { en: "Never fetched", ne: "कहिल्यै नलिइएको" },
  run_ok: { en: "Ran", ne: "चल्यो" },
  run_error: { en: "Failed", ne: "असफल" },
  /* `Severity`, which the report detail was printing under the heading "Status". */
  sev_low: { en: "Low", ne: "न्यून" },
  sev_moderate: { en: "Moderate", ne: "मध्यम" },
  sev_high: { en: "High", ne: "उच्च" },
  sev_severe: { en: "Severe", ne: "गम्भीर" },
  sev_unknown: { en: "Severity unknown", ne: "गम्भीरता थाहा छैन" },
  /* The heading a severity needs before it can be named: `severity` is not `status`, and on the
     report detail it was being printed under the label that `verification_status` owns. */
  severity: { en: "Severity", ne: "गम्भीरता" },
  /* The two-letter code is a fact about storage; the reader needs the name. */
  language_en: { en: "English", ne: "अंग्रेजी" },
  language_ne: { en: "Nepali", ne: "नेपाली" },
  source_notes: { en: "Notes", ne: "टिप्पणी" },
  activity_intro: {
    en: "What the platform did, in the order it did it.",
    ne: "प्लेटफर्मले के गर्यो, गरेको क्रममा।",
  },
  audit_intro: {
    en: "Every change a person made, with what the record was before.",
    ne: "मान्छेले गरेका हरेक परिवर्तन, पहिले रेकर्ड के थियो भन्ने सहित।",
  },
  filter_entity: { en: "Record type", ne: "रेकर्ड प्रकार" },
  /* The audit trail's `entity_type` values, singular: one row is one record, not a list of them. */
  entity_incident: { en: "Situation", ne: "घटना" },
  entity_report: { en: "Report", ne: "खबर" },
  entity_assistance_request: { en: "Help request", ne: "सहयोग अनुरोध" },
  entity_resource: { en: "Facility", ne: "सुविधा" },
  entity_source: { en: "Data source", ne: "डाटा स्रोत" },
  entity_user: { en: "Account", ne: "खाता" },
  assistant_intro: {
    en: "Ask the assistant to investigate one situation, or put a victim's report in front of it. It reads the records the console reads; where it may change something, that change is bounded by fixed rules and it is shown below.",
    ne: "कुनै एक घटनाको अनुसन्धान गर्न सहायकलाई भन्नुहोस्, वा पीडितको खबर त्यसै अगाडि राख्नुहोस्। यसले कन्सोलले पढ्ने रेकर्ड पढ्छ; कतै केही बदल्ने ठाउँ छ भने त्यो परिवर्तन स्थिर नियमबाट सीमित हुन्छ र तल देखाइन्छ।",
  },
  agent_provider: { en: "Provider", ne: "प्रदायक" },
  agent_model: { en: "Model", ne: "मोडेल" },
  agent_credentials: { en: "Credentials present", ne: "क्रेडेन्सियल उपलब्ध" },
  agent_fallback_reason: { en: "Why", ne: "किन" },
  agent_runs_total: { en: "Runs recorded", ne: "दर्ता भएका चाल" },
  answer_title: { en: "The language layer", ne: "भाषा तह" },
  agent_available: { en: "Language model", ne: "भाषा मोडेल" },
  answer_how: { en: "How it was written", ne: "कसरी लेखियो" },
  duration: { en: "Time taken", ne: "लागेको समय" },
  agent_history: { en: "Previous runs", ne: "अघिल्ला चालहरू" },
  agent_tools_title: { en: "Tools it may use", ne: "यसले प्रयोग गर्न सक्ने औजार" },
  /* Was "read only - the assistant cannot change a record", which stopped being true the day
     the responder's set went into this inventory. The note has to describe both groups. */
  agent_tools_readonly: {
    en: "The investigation set can only read. The response set additionally files a help request, notes it, notifies the center and messages the caller - and it cannot move any request's status.",
    ne: "अनुसन्धान सेटले पढ्न मात्र सक्छ। प्रतिक्रिया सेटले थप सहयोग अनुरोध दर्ता गर्छ, टिप्पणी गर्छ, केन्द्रलाई खबर गर्छ र खबरकर्तालाई सन्देश पठाउँछ - तर कुनै अनुरोधको स्थिति बदल्न सक्दैन।",
  },
  agent_tool_set: { en: "Set", ne: "सेट" },
  agent_tool_writes: { en: "Changes a record", ne: "रेकर्ड बदल्छ" },
  agent_tool_args: { en: "Arguments", ne: "तर्कहरू" },
  investigate_incident: { en: "Investigate a situation", ne: "घटनाको अनुसन्धान गर्नुहोस्" },
  investigate_hint: {
    en: "An incident id or its reference code.",
    ne: "घटनाको आइडी वा सन्दर्भ कोड।",
  },
  investigate_run: { en: "Run the investigation", ne: "अनुसन्धान चलाउनुहोस्" },
  agent_duration: { en: "Took {ms} ms", ne: "{ms} मिलिसेकेन्ड लाग्यो" },
  known_facts: { en: "Established", ne: "पक्का भएका कुरा" },
  rejected_numbers: { en: "Numbers it refused to use", ne: "यसले प्रयोग गर्न नमानेका अङ्क" },
  agent_history_note: {
    en: "Each question is answered on its own; the assistant does not remember the previous one.",
    ne: "हरेक प्रश्न छुट्टै जवाफ दिइन्छ; सहायकले अघिल्लो प्रश्न सम्झँदैन।",
  },

  /* the audit trail's own words. `action` comes from `shared.enums.AuditAction` plus a few raw
     strings the services write directly; a value added later arrives unmapped and `enumLabel`
     prints it as it came, which beats a blank column that looks like nothing happened. */
  act_login: { en: "Signed in", ne: "साइन इन" },
  act_acknowledge: { en: "Request acknowledged", ne: "अनुरोध स्वीकारियो" },
  act_assign: { en: "Team assigned", ne: "टोली तोकियो" },
  act_status_change: { en: "Status changed", ne: "स्थिति बदलियो" },
  act_verify: { en: "Checked by staff", ne: "कर्मचारीले जाँचे" },
  act_request_verification: { en: "Check asked for", ne: "जाँच मागियो" },
  act_link_report: { en: "Report linked", ne: "खबर जोडियो" },
  act_link_observation: { en: "Observation linked", ne: "अवलोकन जोडियो" },
  act_merge_incidents: { en: "Situations merged", ne: "घटनाहरू जोडिए" },
  act_split_incident: { en: "Situation split", ne: "घटना छुट्याइयो" },
  act_victim_update_sent: { en: "Update sent to the person", ne: "व्यक्तिलाई जानकारी पठाइयो" },
  act_note_added: { en: "Note added", ne: "टिप्पणी थपियो" },
  act_escalate: { en: "Escalated", ne: "माथि पठाइयो" },
  act_resolve: { en: "Resolved", ne: "समाधान गरियो" },
  act_resource_update: { en: "Facility updated", ne: "सुविधा अद्यावधिक" },
  act_demo_inject: { en: "Rehearsal control", ne: "अभ्यास नियन्त्रण" },
  act_agent_investigation: { en: "Assistant ran", ne: "सहायक चल्यो" },
  act_incident_status: { en: "Situation status changed", ne: "घटनाको स्थिति बदलियो" },
  act_offline_flush: { en: "Offline messages sent", ne: "अफलाइन सन्देश पठाइयो" },
  act_report_submitted: { en: "Report submitted", ne: "खबर पेश गरियो" },
  act_request_created: { en: "Help request created", ne: "सहयोग अनुरोध बन्यो" },

  /* `actor_kind` is written explicitly by `services/audit.py` because the four carry different
     authority: a coordinator's confirmation and the platform's own are not the same claim. */
  kind_operator: { en: "Staff", ne: "कर्मचारी" },
  kind_victim: { en: "The person who asked", ne: "अनुरोध गर्ने व्यक्ति" },
  kind_system: { en: "The platform itself", ne: "प्लेटफर्म आफैँ" },
  kind_agent: { en: "Assistant", ne: "सहायक" },

  /* `entity_type='system'` is what arming and disarming a rehearsal writes, so the filter has
     to offer it or those rows can never be found. */
  entity_system: { en: "Platform", ne: "प्लेटफर्म" },
  col_record: { en: "Record", ne: "रेकर्ड" },
  col_summary: { en: "What happened", ne: "के भयो" },
  audit_entity_id_hint: {
    en: "A record id narrows the list only when a record type is chosen with it.",
    ne: "रेकर्ड प्रकार पनि छानेको खण्डमा मात्र रेकर्ड आइडीले सूची छान्छ।",
  },
  activity_is_audit: {
    en: "This is the audit trail read as a feed: the same rows, with what changed summarised.",
    ne: "यो अडिट लगलाई फिडको रूपमा देखाइएको हो: उही पङ्क्तिहरू, परिवर्तनको सारांश सहित।",
  },
  agent_runs_note: {
    en: "Every run is stored, including the ones whose wording was refused.",
    ne: "हरेक चाल संग्रह गरिन्छ, शब्द अस्वीकार भएका पनि।",
  },
  agent_status_completed: { en: "Answered", ne: "जवाफ दिइयो" },
  agent_status_rejected_unverified_numbers: {
    en: "Wording refused - it used numbers no record contains",
    ne: "शब्द अस्वीकृत - कुनै रेकर्डमा नभएका अङ्क प्रयोग गर्यो",
  },
  agent_status_model_error: { en: "The language layer failed", ne: "भाषा तह असफल भयो" },
  agent_tool_calls: { en: "Tools it called", ne: "यसले बोलाएका औजार" },

  /* The responder: one victim report, run end to end, with its activity shown. */
  respond_title: { en: "Answer a victim report", ne: "पीडितको खबरको जवाफ दिनुहोस्" },
  respond_hint: {
    en: "The report as it arrived, in the caller's own words. This run can file a help request; it cannot change a status.",
    ne: "जसरी खबर आयो उही शब्दमा। यस चालले सहयोग अनुरोध दर्ता गर्न सक्छ; स्थिति बदल्न सक्दैन।",
  },
  respond_placeholder: {
    en: "What the caller said, word for word",
    ne: "खबरकर्ताले भनेको जस्तो छ मन्तव्य",
  },
  respond_run: { en: "Put this report in front of the agent", ne: "यो खबर सहायकअगाडि राख्नुहोस्" },
  respond_report_id: { en: "Community report", ne: "समुदायिक खबर" },
  respond_report_hint: {
    en: "Optional. A request is filed for the reporter on that row - the words in this box never name a person.",
    ne: "वैकल्पिक। अनुरोध त्यो पङ्क्तिका खबरकर्ताको नामले दर्ता हुन्छ - यो बाकसका शब्दले कसैको नाम लिँदैनन्।",
  },
  respond_model_calls: { en: "Model calls", ne: "मोडेलका कल" },
  respond_filed: { en: "Requests filed", ne: "दर्ता भएका अनुरोध" },
  respond_reading: { en: "What the fixed rules read", ne: "स्थिर नियमले पढेको कुरा" },
  respond_help_types: { en: "Help asked for", ne: "मागिएको सहयोग" },
  respond_coordinate: {
    en: "Coordinate from the place name",
    ne: "स्थानको नामबाट आएको निर्देशाङ्क",
  },
  respond_reading_note: {
    en: "Risk words come from a keyword table over the report, not from the model - they are what the priority score is computed from.",
    ne: "जोखिमका शब्द खबरमा लागू भएको शब्द-सूचीबाट आएका हुन्, मोडेलबाट होइनन् - तिनीहरूबाटै प्राथमिकता गणना हुन्छ।",
  },
  respond_location: { en: "Location from the words", ne: "शब्दबाट स्थान" },
  respond_none: { en: "Nothing was filed", ne: "केही दर्ता भएन" },
  activity_title: { en: "What the agent did", ne: "एजेन्टले के गर्यो" },
  activity_note: {
    en: "Step and tool names with their time, status and result - and not the model's reasoning, which this system does not record.",
    ne: "चरण र औजारका नाम, तिनको समय, स्थिति र नतिजा - मोडेलको तर्क होइन, जुन यस प्रणालीले दर्ता नै गर्दैन।",
  },
  activity_step: { en: "Step", ne: "चरण" },
  activity_when: { en: "When", ne: "कहिले" },
  activity_kind_phase: { en: "A step every run does", ne: "हरेक चालले गर्ने चरण" },
  activity_kind_tool: { en: "A tool the agent chose to call", ne: "एजेन्टले आफै छानेको औजार" },
  astep_ok: { en: "Ran", ne: "चल्यो" },
  astep_empty: { en: "Ran, found nothing", ne: "चल्यो, केही भेटिएन" },
  astep_warning: { en: "Ran with a warning", ne: "चेतावनी सहित चल्यो" },
  astep_refused: { en: "Refused by a guardrail", ne: "सीमाले अस्वीकार गर्यो" },
  astep_error: { en: "Failed", ne: "असफल" },
  activity_none: {
    en: "This run recorded no steps. It did not read or change anything.",
    ne: "यस चालले कुनै चरण दर्ता गरेन। यसले केही पढेन वा बदलेन।",
  },
  step_received_report: { en: "Received report", ne: "खबर प्राप्त भयो" },
  step_understanding_request: { en: "Understanding request", ne: "अनुरोध बुझिँदै" },
  step_selecting_checks: { en: "Choosing which checks matter", ne: "कुन जाँच महत्त्वपूर्ण छ छानिँदै" },
  step_filing_from_rules: { en: "Filed by the rules", ne: "नियमबाट दर्ता भयो" },
  step_evaluating_priority: { en: "Evaluating priority", ne: "प्राथमिकता मूल्याङ्कन" },
  step_creating_assistance_request: {
    en: "Creating assistance request",
    ne: "सहयोग अनुरोध बनाइँदै",
  },
  step_completed: { en: "Completed", ne: "पूरा भयो" },
  investigate_placeholder: { en: "An incident id or its reference code", ne: "घटनाको आइडी वा सन्दर्भ कोड" },
  assistant_no_runs: {
    en: "The assistant has not run for this situation yet.",
    ne: "यस घटनाका लागि सहायक अझै चलेको छैन।",
  },

  map_unplaced: {
    en: "{count} records in this layer have no coordinates and cannot be drawn",
    ne: "यस तहका {count} रेकर्डमा निर्देशांक छैन, कोर्न सकिँदैन",
  },
  map_layer_unavailable: { en: "not available on this server", ne: "यो सर्भरमा उपलब्ध छैन" },
  affected: { en: "Affected", ne: "प्रभावित" },
  magnitude: { en: "Magnitude", ne: "परिमाण" },
  availability: { en: "Availability", ne: "उपलब्धता" },
  capacity: { en: "Capacity", ne: "क्षमता" },
  contact_verified: { en: "Contact verified", ne: "सम्पर्क प्रमाणित" },
  yes: { en: "Yes", ne: "हो" },
  no: { en: "No", ne: "होइन" },
  open_source: { en: "Official source", ne: "आधिकारिक स्रोत" },
  people_count: { en: "People needing help", ne: "सहयोग चाहिने मान्छे" },
  urgency_reasons: { en: "Why this is urgent", ne: "किन तत्काल मानिएको" },
  layer_signals: { en: "Risk signals", ne: "जोखिम संकेत" },
  paused: { en: "paused", ne: "रोकिएको" },

  rank_operator: { en: "Operator", ne: "सञ्चालक" },
  rank_coordinator: { en: "Coordinator", ne: "समन्वयक" },
  rank_analyst: { en: "Analyst", ne: "विश्लेषक" },
  rank_community_member: { en: "Community member", ne: "समुदायका सदस्य" },
} satisfies Record<string, Record<Language, string>>;

export type StringKey = keyof typeof STRINGS;

/** The enum suffixes, so `urgency_${row.urgency}` resolves through one lookup. */
export const URGENCY_KEYS = {
  critical: "urgency_critical",
  urgent: "urgency_urgent",
  attention: "urgency_attention",
  information: "urgency_information",
} as const satisfies Record<string, StringKey>;

export const EVIDENCE_KEYS = {
  officially_confirmed: "evidence_officially_confirmed",
  officially_reported: "evidence_officially_reported",
  corroborated: "evidence_corroborated",
  community_reported: "evidence_community_reported",
  conflicting: "evidence_conflicting",
  unverified: "evidence_unverified",
} as const satisfies Record<string, StringKey>;

export const FRESHNESS_KEYS = {
  fresh: "freshness_fresh",
  recent: "freshness_recent",
  aging: "freshness_aging",
  stale: "freshness_stale",
  unknown: "freshness_unknown",
} as const satisfies Record<string, StringKey>;

export const PRECISION_KEYS = {
  source_coordinate: "precision_source_coordinate",
  named_place: "precision_named_place",
  local_level: "precision_local_level",
  district_centroid: "precision_district_centroid",
  user_shared: "precision_user_shared",
  unlocated: "precision_unlocated",
} as const satisfies Record<string, StringKey>;

/** The vocabulary `assistance.resolve_location()` writes into `location_confidence`. */
export const LOCATION_CONFIDENCE_KEYS = {
  high: "loc_conf_high",
  medium: "loc_conf_medium",
  low: "loc_conf_low",
  text_only: "loc_conf_text_only",
  inferred_home_district: "loc_conf_inferred_home_district",
  unknown: "loc_conf_unknown",
} as const satisfies Record<string, StringKey>;

/** The same enum, for a screen an operator reads. "Inferred from your home district" is a true
 *  thing to say to the reporter and is addressed to the wrong person on a console. */
export const LOCATION_CONFIDENCE_KEYS_STAFF: Record<string, StringKey> = {
  ...LOCATION_CONFIDENCE_KEYS,
  inferred_home_district: "loc_conf_inferred_home_district_staff",
};

/** `SourceStatus` and an ingestion run's result - two vocabularies, deliberately not merged: a
 *  healthy source can have a failed last run, and a failing source can have a successful one. */
export const SOURCE_STATUS_KEYS = {
  healthy: "src_healthy",
  degraded: "src_degraded",
  failing: "src_failing",
  disabled: "src_disabled",
  never_fetched: "src_never_fetched",
} as const satisfies Record<string, StringKey>;

export const RUN_STATUS_KEYS = {
  ok: "run_ok",
  error: "run_error",
} as const satisfies Record<string, StringKey>;

/** `Severity`. */
export const SEVERITY_KEYS = {
  low: "sev_low",
  moderate: "sev_moderate",
  high: "sev_high",
  severe: "sev_severe",
  unknown: "sev_unknown",
} as const satisfies Record<string, StringKey>;

/** The `language` field on a report or a request, named in the reader's own language. */
export const LANGUAGE_NAME_KEYS = {
  en: "language_en",
  ne: "language_ne",
} as const satisfies Record<string, StringKey>;

/** `ResourceType`, in the order a coordinator scans for them: medical first, contact last. */
export const RESOURCE_TYPE_KEYS = {
  hospital: "rt_hospital",
  health_post: "rt_health_post",
  ambulance: "rt_ambulance",
  shelter: "rt_shelter",
  police: "rt_police",
  army: "rt_army",
  fire: "rt_fire",
  water_supply: "rt_water_supply",
  food_distribution: "rt_food_distribution",
  helipad: "rt_helipad",
  emergency_contact: "rt_emergency_contact",
} as const satisfies Record<string, StringKey>;

/** `Availability`. `unknown` is a real answer here, not a missing one. */
export const AVAILABILITY_KEYS = {
  available: "av_available",
  limited: "av_limited",
  closed: "av_closed",
  unknown: "av_unknown",
} as const satisfies Record<string, StringKey>;

/** The `entity_type` values `services/audit.py` writes, plus the `system` rows arming and
 *  disarming a rehearsal produces. */
export const ENTITY_KEYS = {
  incident: "entity_incident",
  report: "entity_report",
  assistance_request: "entity_assistance_request",
  resource: "entity_resource",
  source: "entity_source",
  user: "entity_user",
  system: "entity_system",
} as const satisfies Record<string, StringKey>;

/** `AuditAction`, plus the raw action strings the services write without going through it. */
export const ACTION_KEYS = {
  login: "act_login",
  acknowledge: "act_acknowledge",
  assign: "act_assign",
  status_change: "act_status_change",
  verify: "act_verify",
  request_verification: "act_request_verification",
  link_report: "act_link_report",
  link_observation: "act_link_observation",
  merge_incidents: "act_merge_incidents",
  split_incident: "act_split_incident",
  victim_update_sent: "act_victim_update_sent",
  note_added: "act_note_added",
  escalate: "act_escalate",
  resolve: "act_resolve",
  resource_update: "act_resource_update",
  demo_inject: "act_demo_inject",
  agent_investigation: "act_agent_investigation",
  incident_status: "act_incident_status",
  offline_flush: "act_offline_flush",
  report_submitted: "act_report_submitted",
  request_created: "act_request_created",
} as const satisfies Record<string, StringKey>;

/** Who acted. The distinction carries authority, so it is a column and not a detail. */
export const ACTOR_KIND_KEYS = {
  operator: "kind_operator",
  victim: "kind_victim",
  system: "kind_system",
  agent: "kind_agent",
} as const satisfies Record<string, StringKey>;

/** `AgentInvestigation.status`. The rejected one is the important label: it is the trust
 *  model saying out loud that a model's wording was thrown away. */
export const AGENT_STATUS_KEYS = {
  completed: "agent_status_completed",
  rejected_unverified_numbers: "agent_status_rejected_unverified_numbers",
  model_error: "agent_status_model_error",
} as const satisfies Record<string, StringKey>;

/** The fixed spine of a responder run, keyed by the upper-case action the API emits. Only the
 *  steps this workflow performs itself are listed: a tool's own name is the server's inventory
 *  speaking, so `enumLabel` passes it through untranslated rather than inventing a label for a
 *  name that is published elsewhere in this app. */
export const AGENT_ACTIVITY_KEYS = {
  RECEIVED_REPORT: "step_received_report",
  UNDERSTANDING_REQUEST: "step_understanding_request",
  SELECTING_CHECKS: "step_selecting_checks",
  FILING_FROM_RULES: "step_filing_from_rules",
  EVALUATING_PRIORITY: "step_evaluating_priority",
  CREATING_ASSISTANCE_REQUEST: "step_creating_assistance_request",
  COMPLETED: "step_completed",
} as const satisfies Record<string, StringKey>;

/** One activity step's outcome. `refused` and `empty` are the two that matter: a guardrail that
 *  stopped the agent, and a check that came back with nothing in it, both have to be visible
 *  rather than looking like a step that quietly never happened. */
export const AGENT_STEP_STATUS_KEYS = {
  ok: "astep_ok",
  empty: "astep_empty",
  warning: "astep_warning",
  refused: "astep_refused",
  error: "astep_error",
} as const satisfies Record<string, StringKey>;

export const HAZARD_KEYS = {
  flood: "type_flood",
  landslide: "type_landslide",
  earthquake: "type_earthquake",
  heavy_rainfall: "type_heavy_rainfall",
  storm: "type_storm",
  lightning: "type_lightning",
  fire: "type_fire",
  road_blockage: "type_road_blockage",
  infrastructure_damage: "type_infrastructure_damage",
  other: "type_other",
} as const satisfies Record<string, StringKey>;

/** What a person asks for. The values are `AssistanceType`, and the order is §21's. */
export const ASSISTANCE_TYPE_KEYS = {
  medical: "assist_medical",
  rescue: "assist_rescue",
  food: "assist_food",
  water: "assist_water",
  shelter: "assist_shelter",
  transport: "assist_transport",
  information: "assist_information",
  other: "assist_other",
} as const satisfies Record<string, StringKey>;

/** `ReportType`. Note `sought_person` and `offered_help`, whose values are not the suffixes. */
export const REPORT_TYPE_KEYS = {
  incident: "rtype_incident",
  condition: "rtype_condition",
  damage: "rtype_damage",
  sought_person: "rtype_sought_person",
  offered_help: "rtype_offered_help",
} as const satisfies Record<string, StringKey>;

/** `VerificationStatus` - who has believed this report so far. */
export const VERIFICATION_KEYS = {
  pending: "verify_pending",
  verified: "verify_verified",
  rejected: "verify_rejected",
  duplicate: "verify_duplicate",
  conflicting: "verify_conflicting",
} as const satisfies Record<string, StringKey>;

export const RANK_KEYS = {
  operator: "rank_operator",
  coordinator: "rank_coordinator",
  analyst: "rank_analyst",
  community_member: "rank_community_member",
} as const satisfies Record<string, StringKey>;

/** A help request's lifecycle, in the order the transition table allows it. */
export const ASSISTANCE_STATUS_KEYS = {
  received: "status_received",
  reviewing: "status_reviewing",
  response_team_notified: "status_response_team_notified",
  assigned: "status_assigned",
  in_progress: "status_in_progress",
  resolved: "status_resolved",
  cancelled: "status_cancelled",
} as const satisfies Record<string, StringKey>;

export const INCIDENT_STATUS_KEYS = {
  active: "incident_status_active",
  monitoring: "incident_status_monitoring",
  contained: "incident_status_contained",
  resolved: "incident_status_resolved",
  archived: "incident_status_archived",
} as const satisfies Record<string, StringKey>;

/** The two things the action queue can contain, and the screen each one opens. */
export const QUEUE_KIND_KEYS = {
  assistance_request: "queue_kind_assistance_request",
  incident_review: "queue_kind_incident_review",
} as const satisfies Record<string, StringKey>;

export const PROVENANCE_KEYS = {
  official: "provenance_official",
  community: "provenance_community",
  derived: "provenance_derived",
  operator: "provenance_operator",
  open_data: "provenance_open_data",
  demo: "provenance_demo",
} as const satisfies Record<string, StringKey>;

export function lookup(key: StringKey, language: Language): string {
  const entry = STRINGS[key];
  // An empty translation is treated as "not translated", never as "show nothing".
  return entry[language].trim() ? entry[language] : entry.en;
}

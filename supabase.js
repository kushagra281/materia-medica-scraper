// ================================================================
// Supabase setup for "Homeo for All" React App
// ================================================================
// 1. Install: npm install @supabase/supabase-js
// 2. Get your keys from Supabase → Settings → API
// 3. Create .env file in your React project root with:
//    REACT_APP_SUPABASE_URL=https://rtfjnfepikhahzospnqq.supabase.co
//    REACT_APP_SUPABASE_ANON_KEY=your_anon_key_here
// ================================================================

import { createClient } from '@supabase/supabase-js'

const supabase = createClient(
  process.env.REACT_APP_SUPABASE_URL,
  process.env.REACT_APP_SUPABASE_ANON_KEY
)

export default supabase


// ================================================================
// EXAMPLE FUNCTIONS — copy these into your components
// ================================================================


// 1. Get all remedies (for remedy list page)
export async function getAllRemedies() {
  const { data, error } = await supabase
    .from('remedies')
    .select('id, slug, name, common_name, section_count')
    .order('name')

  if (error) console.error(error)
  return data
}


// 2. Get single remedy with all sections (for remedy detail page)
export async function getRemedyBySlug(slug) {
  const { data: remedy, error } = await supabase
    .from('remedies')
    .select('*')
    .eq('slug', slug)
    .single()

  if (error) console.error(error)

  const { data: sections } = await supabase
    .from('remedy_sections')
    .select('heading, heading_order, content')
    .eq('remedy_id', remedy.id)
    .order('heading_order')

  return { ...remedy, sections }
}


// 3. Search remedies by name (search bar)
export async function searchRemediesByName(query) {
  const { data, error } = await supabase
    .from('remedies')
    .select('id, slug, name, common_name')
    .or(`name.ilike.%${query}%,common_name.ilike.%${query}%`)
    .order('name')
    .limit(20)

  if (error) console.error(error)
  return data
}


// 4. Search by symptom (MOST USEFUL — find remedies for a symptom)
export async function searchBySymptom(symptom) {
  const { data, error } = await supabase
    .from('remedy_symptoms')
    .select('remedy_name, heading, symptom')
    .ilike('symptom', `%${symptom}%`)
    .order('remedy_name')
    .limit(50)

  if (error) console.error(error)
  return data
}


// 5. Get all symptoms for a remedy grouped by body part
export async function getSymptomsByRemedy(remedyId) {
  const { data, error } = await supabase
    .from('remedy_symptoms')
    .select('heading, symptom, symptom_order')
    .eq('remedy_id', remedyId)
    .order('symptom_order')

  if (error) console.error(error)

  // Group by heading/body part
  const grouped = {}
  data?.forEach(row => {
    if (!grouped[row.heading]) grouped[row.heading] = []
    grouped[row.heading].push(row.symptom)
  })

  return grouped
}


// 6. Get remedies by body part / heading
export async function getRemediesByBodyPart(bodyPart) {
  const { data, error } = await supabase
    .from('remedy_symptoms')
    .select('remedy_name, symptom')
    .eq('heading', bodyPart)
    .order('remedy_name')

  if (error) console.error(error)
  return data
}


// ================================================================
// EXAMPLE USAGE IN A REACT COMPONENT
// ================================================================

/*
import { searchBySymptom } from './supabase'

function SymptomSearch() {
  const [results, setResults] = useState([])

  const handleSearch = async (e) => {
    const symptom = e.target.value
    if (symptom.length > 2) {
      const data = await searchBySymptom(symptom)
      setResults(data)
    }
  }

  return (
    <div>
      <input
        type="text"
        placeholder="Search symptom e.g. headache, fever..."
        onChange={handleSearch}
      />
      {results.map((r, i) => (
        <div key={i}>
          <strong>{r.remedy_name}</strong> — {r.heading}
          <p>{r.symptom}</p>
        </div>
      ))}
    </div>
  )
}
*/

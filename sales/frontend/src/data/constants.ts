// Option lists for the Discovery form. Departments and titles match the
// backend's title normalizer (app/services/titles.py) so filters line up.

export const LOCATIONS: { city: string; state: string; country: string }[] = [
  { city: 'Johor Bahru', state: 'Johor', country: 'Malaysia' },
  { city: 'Pasir Gudang', state: 'Johor', country: 'Malaysia' },
  { city: 'Senai', state: 'Johor', country: 'Malaysia' },
  { city: 'Kulai', state: 'Johor', country: 'Malaysia' },
  { city: 'Iskandar Puteri', state: 'Johor', country: 'Malaysia' },
  { city: 'Batu Pahat', state: 'Johor', country: 'Malaysia' },
  { city: 'Kuala Lumpur', state: 'Kuala Lumpur', country: 'Malaysia' },
  { city: 'Shah Alam', state: 'Selangor', country: 'Malaysia' },
  { city: 'Petaling Jaya', state: 'Selangor', country: 'Malaysia' },
  { city: 'Bayan Lepas', state: 'Penang', country: 'Malaysia' },
  { city: 'George Town', state: 'Penang', country: 'Malaysia' },
  { city: 'Singapore', state: 'Singapore', country: 'Singapore' },
];

export const INDUSTRIES = ['Manufacturing', 'Engineering', 'Electrical', 'Electronics', 'Automation', 'Semiconductor',
  'Technology', 'Logistics', 'Construction'];

export const DEPARTMENTS = ['HR', 'L&D', 'IT', 'Engineering', 'Operations', 'Management'];

export const TITLE_NAMES = [
  'HR Manager', 'HR Director', 'Head of HR', 'L&D Manager', 'Head of L&D', 'Training Manager', 'Talent Development Manager',
  'People & Culture Manager', 'IT Manager', 'Head of IT', 'IT Director', 'CIO', 'CTO', 'Digital Transformation Manager',
  'Technology Manager', 'Engineering Manager', 'Engineering Director', 'Head of Engineering', 'Automation Manager',
  'Technical Manager', 'Operations Manager', 'General Manager', 'Managing Director', 'CEO', 'COO',
];

from pathlib import Path

root = Path(__file__).resolve().parents[2] / "target"

(root / "src/amplify-config.ts").write_text("""import { Amplify } from 'aws-amplify';

const userPoolId = process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID;
const userPoolClientId = process.env.NEXT_PUBLIC_COGNITO_USER_POOL_CLIENT_ID;

export const isAmplifyConfigured = Boolean(userPoolId && userPoolClientId);

export function configureAmplify(): void {
  if (!isAmplifyConfigured) return;
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: userPoolId as string,
        userPoolClientId: userPoolClientId as string,
      },
    },
  });
}
""")

(root / ".env.example").write_text("""NEXT_PUBLIC_COGNITO_USER_POOL_ID=region_example
NEXT_PUBLIC_COGNITO_USER_POOL_CLIENT_ID=exampleclientid
NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN=pk.example
""")

(root / "src/app/navbar.tsx").write_text("""'use client';

import { useAuthenticator } from '@aws-amplify/ui-react';
import Image from 'next/image';
import { useRouter } from 'next/navigation';

const Navbar = () => {
  const { user, signOut } = useAuthenticator((context) => [context.user]);
  const router = useRouter();

  const handleLogout = async () => {
    await signOut();
    router.replace('/');
  };

  return (
    <div className="nav">
      <div className="logo">
        <Image src="/assets/Peta_logo.svg" alt="PetaBencana" width={150} height={50} priority />
      </div>
      <div className="email">{user?.signInDetails?.loginId ?? ''}</div>
      <button type="button" className="rounded-button logout" onClick={handleLogout}>
        Logout
      </button>
    </div>
  );
};

export default Navbar;
""")

(root / "src/app/page.tsx").write_text("""'use client';

import { useAuthenticator } from '@aws-amplify/ui-react';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

export default function Home() {
  const { authStatus } = useAuthenticator((context) => [context.authStatus]);
  const router = useRouter();

  useEffect(() => {
    if (authStatus === 'authenticated') router.replace('/map');
  }, [authStatus, router]);

  return <main><p>Opening the resource exchange map…</p></main>;
}
""")

(root / "src/app/layout.tsx").write_text("""'use client';

import { Inter } from 'next/font/google';
import { Authenticator, useAuthenticator } from '@aws-amplify/ui-react';
import '@aws-amplify/ui-react/styles.css';
import './globals.css';
import Navbar from './navbar';
import { configureAmplify, isAmplifyConfigured } from '../amplify-config';

configureAmplify();

const inter = Inter({ subsets: ['latin'] });

function AppShell({ children }: { children: React.ReactNode }) {
  const { authStatus } = useAuthenticator((context) => [context.authStatus]);

  if (!isAmplifyConfigured) {
    return (
      <main>
        <h1>Authentication configuration required</h1>
        <p>Set the documented public Cognito environment variables before deployment.</p>
      </main>
    );
  }
  if (authStatus === 'configuring') return <p>Loading…</p>;
  if (authStatus !== 'authenticated') return <Authenticator />;

  return <><Navbar />{children}</>;
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <Authenticator.Provider>
          <AppShell>{children}</AppShell>
        </Authenticator.Provider>
      </body>
    </html>
  );
}
""")

(root / "src/app/map/components/Legend.tsx").write_text("""import Image from 'next/image';
import styles from './base_layout.module.css';

const gaugeLevelNames: Record<number, string> = {
  1: 'Siaga I', 2: 'Siaga II', 3: 'Siaga III', 4: 'Siaga IV',
};

const Legend = () => (
  <div className={`${styles.leafletBottom} ${styles.leafletRight}`}>
    <div className={`${styles.info} ${styles.legend}`}>
      <div id="reportsLegend">
        <div className={styles.sublegend}>
          <div><Image src="/assets/floodsIcon.svg" width={22} height={22} alt="Flood report" style={{ verticalAlign: 'middle' }} /><span>&nbsp; Laporan Banjir</span></div>
        </div>
      </div>
      <div id="heightsLegend">
        <div className={styles.sublegend}>
          <div style={{ fontWeight: 'bold' }}>Tinggi Banjir</div>
          <div><i className={styles.color} style={{ background: '#CC2A41' }} /><span>&nbsp;&gt; 150 cm</span></div>
          <div><i className={styles.color} style={{ background: '#FF8300' }} /><span>&nbsp;71 cm – 150 cm</span></div>
          <div><i className={styles.color} style={{ background: '#FFFF00' }} /><span>&nbsp;10 cm – 70 cm</span></div>
          <div><i className={styles.color} style={{ background: '#A0A9F7' }} /><span>&nbsp;Hati-hati</span></div>
        </div>
      </div>
      <div id="gaugesLegend">
        <div className={styles.sublegend}>
          <div style={{ fontWeight: 'bold' }}>Tinggi Muka Air</div>
          {[1, 2, 3, 4].map((level) => (
            <div key={level}><Image src={`/assets/floodgauge_${level}.svg`} width={24} height={24} alt={`Flood gauge ${gaugeLevelNames[level]}`} style={{ verticalAlign: 'middle' }} /><span>&nbsp;{gaugeLevelNames[level]}</span></div>
          ))}
        </div>
      </div>
    </div>
  </div>
);

export default Legend;
""")

(root / "src/app/map/components/base_layout.tsx").write_text("""'use client';

import { useMemo, useState } from 'react';
import LeafletMap from './LeafletMap';
import GeoJsonTable from './GeoJsonTable';
import style from './base_layout.module.css';
import { convertTopoJSONToGeoJSON } from './ConvertToGeoJson';
import sampleTopoJsonData from '../topojson.json';

const MapPage = () => {
  const initialGeoJson: any = useMemo(() => convertTopoJSONToGeoJSON(sampleTopoJsonData), []);
  const [selectedDistrict, setSelectedDistrict] = useState('');
  const [selectedVillage, setSelectedVillage] = useState('');
  const [isPolygonMarked, setIsPolygonMarked] = useState(true);

  const features: any[] = initialGeoJson?.features ?? [];
  const handleSelectChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const [district, village] = event.target.value.split('|');
    setSelectedDistrict(district);
    setSelectedVillage(village);
  };

  return (
    <>
      <LeafletMap geoJsonData={initialGeoJson} isPolygonMarked={isPolygonMarked} />
      <div className={style.contentDiv}>
        <label>
          Area
          <select onChange={handleSelectChange} value={`${selectedDistrict}|${selectedVillage}`}>
            <option value="|">Select</option>
            {features.map((feature) => (
              <option key={feature.properties.area_id} value={`${feature.properties.parent_name}|${feature.properties.area_name}`}>
                {feature.properties.area_name} - {feature.properties.parent_name}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => setIsPolygonMarked((marked) => !marked)} className={style.updateBtn}>
          {isPolygonMarked ? 'Hide flood polygons' : 'Show flood polygons'}
        </button>
        {initialGeoJson && selectedVillage && <GeoJsonTable geoJsonData={initialGeoJson} district={selectedDistrict} village={selectedVillage} />}
      </div>
    </>
  );
};

export default MapPage;
""")

(root / "src/app/map/components/LeafletMap.tsx").write_text("""'use client';

import dynamic from 'next/dynamic';
import Legend from './Legend';

const DynamicTileLayer = dynamic(() => import('react-leaflet').then((module) => module.TileLayer), { ssr: false });
const DynamicGeoJSON = dynamic(() => import('react-leaflet').then((module) => module.GeoJSON), { ssr: false });
const DynamicMapContainer = dynamic(() => import('react-leaflet').then((module) => module.MapContainer), { ssr: false });

interface LeafletMapProps { geoJsonData: any; isPolygonMarked: boolean; }

const LeafletMap = ({ geoJsonData, isPolygonMarked }: LeafletMapProps) => {
  const mapboxToken = process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN;
  const tileUrl = mapboxToken
    ? `https://api.mapbox.com/styles/v1/petabencana/ckq0nc6hp01vw17p9n17yxue2/tiles/256/{z}/{x}/{y}@2x?access_token=${mapboxToken}`
    : 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';

  return (
    <>
      <DynamicMapContainer key={isPolygonMarked ? 'marked' : 'not-marked'} center={[-6.172554, 106.80986]} zoom={12} style={{ height: '800px', width: '100%' }}>
        <DynamicTileLayer url={tileUrl} attribution="© OpenStreetMap contributors; map tiles may be provided by Mapbox" />
        {isPolygonMarked && geoJsonData ? <DynamicGeoJSON data={geoJsonData} style={{ fillColor: '#00b5e2', weight: 2, opacity: 1, color: 'gray', fillOpacity: 0.7 }} /> : null}
      </DynamicMapContainer>
      <Legend />
    </>
  );
};

export default LeafletMap;
""")

print("Applied REM latest build, authentication, routing, accessibility, and map-data fixes")

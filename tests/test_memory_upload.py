import base64
from io import BytesIO
import unittest
from python import etl
from python.memory_pipeline import analyze_files
import pandas as pd


def fixture():
    ids=[100000000000000001,100000000000000002,100000000000000003]
    return {'nodes.parquet':pd.DataFrame({'gid':ids,'depth':[0,1,2],'is_seed':[True,False,False]}),
            'edges.parquet':pd.DataFrame({'src':ids[:2],'dst':ids[1:],'sum_kzt':[10000.,10000.],'n_tx':[1,1],'depth':[1,2]}),
            'transactions.parquet':pd.DataFrame({'src':ids[:2],'dst':ids[1:],'sum_kzt':[10000.,10000.],'date':pd.to_datetime(['2025-01-01','2025-01-02'])})}


def encoded(frames):
    result=[]
    for name,frame in frames.items():
        buffer=BytesIO();frame.to_parquet(buffer,index=False)
        result.append({'name':name,'data':base64.b64encode(buffer.getvalue()).decode()})
    return result


class MemoryUploadTests(unittest.TestCase):
    def test_custom_data_not_bound_to_original_counts_or_dates(self):
        result=analyze_files(encoded(fixture()))
        self.assertEqual(len(result['graph']['nodes']),3)
        self.assertEqual(result['graph']['nodes'][0]['gid'],'100000000000000001')
        self.assertEqual(set(result['csvs']),{'nodes_roles.csv','clusters.csv','top_nodes.csv'})
        self.assertEqual(result['graph']['report']['metrics']['sum_in_kzt'],20000)

    def test_bad_names_columns_and_mismatch(self):
        data=encoded(fixture());data[0]['name']='other.parquet'
        with self.assertRaisesRegex(elt:=etl.IntegrityError,'Expected exactly'):analyze_files(data)
        frames=fixture();frames['nodes.parquet']=frames['nodes.parquet'].drop(columns='is_seed')
        with self.assertRaisesRegex(elt,'missing columns.*is_seed'):analyze_files(encoded(frames))
        frames=fixture();frames['edges.parquet'].loc[0,'sum_kzt']=9999
        with self.assertRaisesRegex(elt,'amount mismatch'):analyze_files(encoded(frames))

    def test_corrupt_parquet(self):
        data=encoded(fixture());data[0]['data']=base64.b64encode(b'not parquet').decode()
        with self.assertRaises(Exception):analyze_files(data)


if __name__=='__main__':unittest.main()

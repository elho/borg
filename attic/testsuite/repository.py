import os
import shutil
import tempfile
from attic.hashindex import NSIndex
from attic.helpers import Location, IntegrityError
from attic.remote import RemoteRepository
from attic.repository import Repository
from attic.testsuite import AtticTestCase


class RepositoryTestCase(AtticTestCase):

    def open(self, create=False):
        return Repository(os.path.join(self.tmppath, 'repository'), create=create)

    def setUp(self):
        self.tmppath = tempfile.mkdtemp()
        self.repository = self.open(create=True)

    def tearDown(self):
        self.repository.close()
        shutil.rmtree(self.tmppath)

    def test1(self):
        for x in range(100):
            self.repository.put(('%-32d' % x).encode('ascii'), b'SOMEDATA')
        key50 = ('%-32d' % 50).encode('ascii')
        self.assert_equal(self.repository.get(key50), b'SOMEDATA')
        self.repository.delete(key50)
        self.assert_raises(Repository.DoesNotExist, lambda: self.repository.get(key50))
        self.repository.commit()
        self.repository.close()
        repository2 = self.open()
        self.assert_raises(Repository.DoesNotExist, lambda: repository2.get(key50))
        for x in range(100):
            if x == 50:
                continue
            self.assert_equal(repository2.get(('%-32d' % x).encode('ascii')), b'SOMEDATA')
        repository2.close()

    def test2(self):
        """Test multiple sequential transactions
        """
        self.repository.put(b'00000000000000000000000000000000', b'foo')
        self.repository.put(b'00000000000000000000000000000001', b'foo')
        self.repository.commit()
        self.repository.delete(b'00000000000000000000000000000000')
        self.repository.put(b'00000000000000000000000000000001', b'bar')
        self.repository.commit()
        self.assert_equal(self.repository.get(b'00000000000000000000000000000001'), b'bar')

    def test_consistency(self):
        """Test cache consistency
        """
        self.repository.put(b'00000000000000000000000000000000', b'foo')
        self.assert_equal(self.repository.get(b'00000000000000000000000000000000'), b'foo')
        self.repository.put(b'00000000000000000000000000000000', b'foo2')
        self.assert_equal(self.repository.get(b'00000000000000000000000000000000'), b'foo2')
        self.repository.put(b'00000000000000000000000000000000', b'bar')
        self.assert_equal(self.repository.get(b'00000000000000000000000000000000'), b'bar')
        self.repository.delete(b'00000000000000000000000000000000')
        self.assert_raises(Repository.DoesNotExist, lambda: self.repository.get(b'00000000000000000000000000000000'))

    def test_consistency2(self):
        """Test cache consistency2
        """
        self.repository.put(b'00000000000000000000000000000000', b'foo')
        self.assert_equal(self.repository.get(b'00000000000000000000000000000000'), b'foo')
        self.repository.commit()
        self.repository.put(b'00000000000000000000000000000000', b'foo2')
        self.assert_equal(self.repository.get(b'00000000000000000000000000000000'), b'foo2')
        self.repository.rollback()
        self.assert_equal(self.repository.get(b'00000000000000000000000000000000'), b'foo')

    def test_single_kind_transactions(self):
        # put
        self.repository.put(b'00000000000000000000000000000000', b'foo')
        self.repository.commit()
        self.repository.close()
        # replace
        self.repository = self.open()
        self.repository.put(b'00000000000000000000000000000000', b'bar')
        self.repository.commit()
        self.repository.close()
        # delete
        self.repository = self.open()
        self.repository.delete(b'00000000000000000000000000000000')
        self.repository.commit()


class RepositoryCheckTestCase(AtticTestCase):

    def open(self, create=False):
        return Repository(os.path.join(self.tmppath, 'repository'), create=create)

    def reopen(self):
        if self.repository:
            self.repository.close()
        self.repository = self.open()

    def setUp(self):
        self.tmppath = tempfile.mkdtemp()
        self.repository = self.open(create=True)

    def tearDown(self):
        self.repository.close()
        shutil.rmtree(self.tmppath)

    def list_indices(self):
        return [name for name in os.listdir(os.path.join(self.tmppath, 'repository')) if name.startswith('index.')]

    def check(self, repair=False, status=True):
        self.assert_equal(self.repository.check(repair=repair), status)
        # Make sure no tmp files are left behind
        self.assert_equal([name for name in os.listdir(os.path.join(self.tmppath, 'repository')) if 'tmp' in name], [], 'Found tmp files')

    def get_objects(self, *ids):
        for id_ in ids:
            self.repository.get(('%032d' % id_).encode('ascii'))

    def add_objects(self, segments):
        for ids in segments:
            for id_ in ids:
                self.repository.put(('%032d' % id_).encode('ascii'), b'data')
            self.repository.commit()

    def get_head(self):
        return sorted(int(n) for n in os.listdir(os.path.join(self.tmppath, 'repository', 'data', '0')) if n.isdigit())[-1]

    def open_index(self):
        return NSIndex(os.path.join(self.tmppath, 'repository', 'index.{}'.format(self.get_head())))

    def corrupt_object(self, id_):
        idx = self.open_index()
        segment, offset = idx[('%032d' % id_).encode('ascii')]
        with open(os.path.join(self.tmppath, 'repository', 'data', '0', str(segment)), 'r+b') as fd:
            fd.seek(offset)
            fd.write(b'BOOM')

    def delete_segment(self, segment):
        os.unlink(os.path.join(self.tmppath, 'repository', 'data', '0', str(segment)))

    def delete_index(self):
        os.unlink(os.path.join(self.tmppath, 'repository', 'index.{}'.format(self.get_head())))

    def rename_index(self, new_name):
        os.rename(os.path.join(self.tmppath, 'repository', 'index.{}'.format(self.get_head())),
                  os.path.join(self.tmppath, 'repository', new_name))

    def list_objects(self):
        return set((int(key) for key, _ in list(self.open_index().iteritems())))

    def test_repair_corrupted_segment(self):
        self.add_objects([[1, 2, 3], [4, 5, 6]])
        self.assert_equal(set([1, 2, 3, 4, 5, 6]), self.list_objects())
        self.check(status=True)
        self.corrupt_object(5)
        self.assert_raises(IntegrityError, lambda: self.get_objects(5))
        self.repository.rollback()
        # Make sure a regular check does not repair anything
        self.check(status=False)
        self.check(status=False)
        # Make sure a repair actually repairs the repo
        self.check(repair=True, status=True)
        self.get_objects(4)
        self.check(status=True)
        self.assert_equal(set([1, 2, 3, 4, 6]), self.list_objects())

    def test_repair_missing_segment(self):
        self.add_objects([[1, 2, 3], [4, 5, 6]])
        self.assert_equal(set([1, 2, 3, 4, 5, 6]), self.list_objects())
        self.check(status=True)
        self.delete_segment(1)
        self.repository.rollback()
        self.check(repair=True, status=True)
        self.assert_equal(set([1, 2, 3]), self.list_objects())

    def test_repair_missing_commit_segment(self):
        self.add_objects([[1, 2, 3], [4, 5, 6]])
        self.delete_segment(1)
        self.assert_raises(Repository.CheckNeeded, lambda: self.get_objects(4))
        self.check(status=False)
        self.assert_raises(Repository.CheckNeeded, lambda: self.get_objects(4))
        self.check(repair=True, status=True)
        self.assert_raises(Repository.DoesNotExist, lambda: self.get_objects(4))
        self.assert_equal(set([1, 2, 3]), self.list_objects())

    def test_repair_corrupted_commit_segment(self):
        self.add_objects([[1, 2, 3], [4, 5, 6]])
        with open(os.path.join(self.tmppath, 'repository', 'data', '0', '1'), 'r+b') as fd:
            fd.seek(-1, os.SEEK_END)
            fd.write(b'X')
        self.assert_raises(Repository.CheckNeeded, lambda: self.get_objects(4))
        self.check(status=False)
        self.check(repair=True, status=True)
        self.get_objects(3)
        self.assert_raises(Repository.DoesNotExist, lambda: self.get_objects(4))
        self.assert_equal(set([1, 2, 3]), self.list_objects())

    def test_repair_no_commits(self):
        self.add_objects([[1, 2, 3]])
        with open(os.path.join(self.tmppath, 'repository', 'data', '0', '0'), 'r+b') as fd:
            fd.seek(-1, os.SEEK_END)
            fd.write(b'X')
        self.assert_raises(Repository.CheckNeeded, lambda: self.get_objects(4))
        self.check(status=False)
        self.check(status=False)
        self.assert_equal(self.list_indices(), ['index.0'])
        self.check(repair=True, status=True)
        self.assert_equal(self.list_indices(), ['index.1'])
        self.check(status=True)
        self.get_objects(3)
        self.assert_equal(set([1, 2, 3]), self.list_objects())

    def test_repair_missing_index(self):
        self.add_objects([[1, 2, 3], [4, 5, 6]])
        self.delete_index()
        self.assert_raises(Repository.CheckNeeded, lambda: self.get_objects(4))
        self.check(status=False)
        self.check(repair=True, status=True)
        self.check(status=True)
        self.get_objects(4)
        self.assert_equal(set([1, 2, 3, 4, 5, 6]), self.list_objects())

    def test_repair_index_too_old(self):
        self.add_objects([[1, 2, 3], [4, 5, 6]])
        self.assert_equal(self.list_indices(), ['index.1'])
        self.rename_index('index.0')
        self.assert_equal(self.list_indices(), ['index.0'])
        self.assert_raises(Repository.CheckNeeded, lambda: self.get_objects(4))
        self.check(status=False)
        self.check(repair=True, status=True)
        self.assert_equal(self.list_indices(), ['index.1'])
        self.check(status=True)
        self.get_objects(4)
        self.assert_equal(set([1, 2, 3, 4, 5, 6]), self.list_objects())

    def test_repair_index_too_new(self):
        self.add_objects([[1, 2, 3], [4, 5, 6]])
        self.assert_equal(self.list_indices(), ['index.1'])
        self.rename_index('index.100')
        self.assert_equal(self.list_indices(), ['index.100'])
        self.assert_raises(Repository.CheckNeeded, lambda: self.get_objects(4))
        self.check(status=False)
        self.check(repair=True, status=True)
        self.assert_equal(self.list_indices(), ['index.1'])
        self.check(status=True)
        self.get_objects(4)
        self.assert_equal(set([1, 2, 3, 4, 5, 6]), self.list_objects())


class RemoteRepositoryTestCase(RepositoryTestCase):

    def open(self, create=False):
        return RemoteRepository(Location('__testsuite__:' + os.path.join(self.tmppath, 'repository')), create=create)


class RemoteRepositoryCheckTestCase(RepositoryCheckTestCase):

    def open(self, create=False):
        return RemoteRepository(Location('__testsuite__:' + os.path.join(self.tmppath, 'repository')), create=create)

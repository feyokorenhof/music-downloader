from typing import List
import musicbrainzngs
import logging

from object_handeling import get_elem_from_obj, parse_music_brainz_date

# I don't know if it would be feesable to set up my own mb instance
# https://github.com/metabrainz/musicbrainz-docker

mb_log = logging.getLogger("musicbrainzngs")
mb_log.setLevel(logging.WARNING)
musicbrainzngs.set_useragent("metadata receiver", "0.1", "https://github.com/HeIIow2/music-downloader")


# IMPORTANT DOCUMENTATION WHICH CONTAINS FOR EXAMPLE THE INCLUDES
# https://python-musicbrainzngs.readthedocs.io/en/v0.7.1/api/#getting-data


class MetadataDownloader:
    def __init__(self, database, logger: logging.Logger):
        self.database = database
        self.logger = logger

    class Artist:
        def __init__(
                self,
                database,
                logger,
                musicbrainz_artistid: str,
                release_groups: List = [],
                new_release_groups: bool = True
        ):
            self.database = database
            self.logger = logger
            """
            release_groups: list
            """
            self.release_groups = release_groups

            self.musicbrainz_artistid = musicbrainz_artistid

            result = musicbrainzngs.get_artist_by_id(self.musicbrainz_artistid, includes=["release-groups", "releases"])
            artist_data = get_elem_from_obj(result, ['artist'], return_if_none={})

            self.artist = get_elem_from_obj(artist_data, ['name'])

            self.save()

            # STARTING TO FETCH' RELEASE GROUPS. IMPORTANT: DON'T WRITE ANYTHING BESIDES THAT HERE
            if not new_release_groups:
                return
            # sort all release groups by date and add album sort to have them in chronological order.
            release_groups = artist_data['release-group-list']
            for i, release_group in enumerate(release_groups):
                release_groups[i]['first-release-date'] = parse_music_brainz_date(release_group['first-release-date'])
            release_groups.sort(key=lambda x: x['first-release-date'])

            for i, release_group in enumerate(release_groups):
                self.release_groups.append(MetadataDownloader.ReleaseGroup(
                    self.database,
                    self.logger,
                    musicbrainz_releasegroupid=release_group['id'],
                    artists=[self],
                    albumsort=i + 1
                ))

        def __str__(self):
            newline = "\n"
            return f"id: {self.musicbrainz_artistid}\nname: {self.artist}\n{newline.join([str(release_group) for release_group in self.release_groups])}"

        def save(self):
            self.logger.info(f"artist: {self}")
            self.database.add_artist(
                musicbrainz_artistid=self.musicbrainz_artistid,
                artist=self.artist
            )

    class ReleaseGroup:
        def __init__(
                self,
                database,
                logger,
                musicbrainz_releasegroupid: str,
                artists = [],
                albumsort: int = None,
                only_download_distinct_releases: bool = True
        ):
            self.database = database
            self.logger = logger
            """
            split_artists: list -> if len > 1: album_artist=VariousArtists
            releases: list
            """

            self.musicbrainz_releasegroupid = musicbrainz_releasegroupid
            self.artists = artists
            self.releases = []

            result = musicbrainzngs.get_release_group_by_id(musicbrainz_releasegroupid,
                                                            includes=["artist-credits", "releases"])
            release_group_data = get_elem_from_obj(result, ['release-group'], return_if_none={})
            artist_datas = get_elem_from_obj(release_group_data, ['artist-credit'], return_if_none={})
            release_datas = get_elem_from_obj(release_group_data, ['release-list'], return_if_none={})

            for artist_data in artist_datas:
                artist_id = get_elem_from_obj(artist_data, ['artist', 'id'])
                if artist_id is None:
                    continue
                self.append_artist(artist_id)
            self.albumartist = "Various Artists" if len(self.artists) > 1 else self.artists[0].artist
            self.album_artist_id = None if self.albumartist == "Various Artists" else self.artists[
                0].musicbrainz_artistid

            self.albumsort = albumsort
            self.musicbrainz_albumtype = get_elem_from_obj(release_group_data, ['primary-type'])
            self.compilation = "1" if self.musicbrainz_albumtype == "Compilation" else None

            self.save()

            if only_download_distinct_releases:
                self.append_distinct_releases(release_datas)
            else:
                self.append_all_releases(release_datas)

        def __str__(self):
            newline = "\n"
            return f"{newline.join([str(release_group) for release_group in self.releases])}"

        def save(self):
            self.logger.info(f"caching release_group {self}")
            self.database.add_release_group(
                musicbrainz_releasegroupid=self.musicbrainz_releasegroupid,
                artist_ids=[artist.musicbrainz_artistid for artist in self.artists],
                albumartist=self.albumartist,
                albumsort=self.albumsort,
                musicbrainz_albumtype=self.musicbrainz_albumtype,
                compilation=self.compilation,
                album_artist_id=self.album_artist_id
            )

        def append_artist(self, artist_id: str):
            for existing_artist in self.artists:
                if artist_id == existing_artist.musicbrainz_artistid:
                    return existing_artist
            new_artist = Artist(artist_id, release_groups=[self], new_release_groups=False)
            self.artists.append(new_artist)
            return new_artist

        def append_release(self, release_data: dict):
            musicbrainz_albumid = get_elem_from_obj(release_data, ['id'])
            if musicbrainz_albumid is None:
                return
            self.releases.append(MetadataDownloader.Release(self.database, self.logger, musicbrainz_albumid, release_group=self))

        def append_distinct_releases(self, release_datas: List[dict]):
            titles = {}

            for release_data in release_datas:
                title = get_elem_from_obj(release_data, ['title'])
                if title is None:
                    continue
                titles[title] = release_data

            for key in titles:
                self.append_release(titles[key])

        def append_all_releases(self, release_datas: List[dict]):
            for release_data in release_datas:
                self.append_release(release_data)

    class Release:
        def __init__(
                self,
                database,
                logger,
                musicbrainz_albumid: str,
                release_group = None
        ):
            self.database = database
            self.logger = logger
            """
            release_group: ReleaseGroup
            tracks: list
            """
            self.musicbrainz_albumid = musicbrainz_albumid
            self.release_group = release_group
            self.tracklist = []

            result = musicbrainzngs.get_release_by_id(self.musicbrainz_albumid, includes=["recordings", "labels"])
            release_data = get_elem_from_obj(result, ['release'], return_if_none={})
            label_data = get_elem_from_obj(release_data, ['label-info-list'], return_if_none={})
            recording_datas = get_elem_from_obj(release_data, ['medium-list', 0, 'track-list'], return_if_none=[])

            self.title = get_elem_from_obj(release_data, ['title'])
            self.copyright = get_elem_from_obj(label_data, [0, 'label', 'name'])

            self.album_status = get_elem_from_obj(release_data, ['status'])
            self.language = get_elem_from_obj(release_data, ['text-representation', 'language'])
            self.year = get_elem_from_obj(release_data, ['date'], lambda x: x.split("-")[0])
            self.date = get_elem_from_obj(release_data, ['date'])
            self.country = get_elem_from_obj(release_data, ['country'])
            self.barcode = get_elem_from_obj(release_data, ['barcode'])

            self.save()
            self.append_recordings(recording_datas)

        def __str__(self):
            return f"{self.title} ©{self.copyright} {self.album_status}"

        def save(self):
            self.logger.info(f"caching release {self}")
            self.database.add_release(
                musicbrainz_albumid=self.musicbrainz_albumid,
                release_group_id=self.release_group.musicbrainz_releasegroupid,
                title=self.title,
                copyright_=self.copyright,
                album_status=self.album_status,
                language=self.language,
                year=self.year,
                date=self.date,
                country=self.country,
                barcode=self.barcode
            )

        def append_recordings(self, recording_datas: dict):
            for recording_data in recording_datas:
                musicbrainz_releasetrackid = get_elem_from_obj(recording_data, ['recording', 'id'])
                if musicbrainz_releasetrackid is None:
                    continue

                self.tracklist.append(MetadataDownloader.Track(self.database, self.logger, musicbrainz_releasetrackid, self))

    class Track:
        def __init__(
                self,
                database,
                logger,
                musicbrainz_releasetrackid: str,
                release = None
        ):
            self.database = database
            self.logger = logger
            """
            release: Release
            feature_artists: list
            """

            self.musicbrainz_releasetrackid = musicbrainz_releasetrackid
            self.release = release
            self.artists = []

            result = musicbrainzngs.get_recording_by_id(self.musicbrainz_releasetrackid,
                                                        includes=["artists", "releases", "recording-rels", "isrcs",
                                                                  "work-level-rels"])
            recording_data = result['recording']
            for artist_data in get_elem_from_obj(recording_data, ['artist-credit'], return_if_none=[]):
                self.append_artist(get_elem_from_obj(artist_data, ['artist', 'id']))

            self.isrc = get_elem_from_obj(recording_data, ['isrc-list', 0])
            self.title = recording_data['title']

            self.save()

        def __str__(self):
            return f"{self.title}: {self.isrc}"

        def save(self):
            self.logger.info(f"caching track {self}")

            self.database.add_track(
                musicbrainz_releasetrackid=self.musicbrainz_releasetrackid,
                musicbrainz_albumid=self.release.musicbrainz_albumid,
                feature_aritsts=[artist.musicbrainz_artistid for artist in self.artists],
                track=self.title,
                isrc=self.isrc
            )

        def append_artist(self, artist_id: str):
            if artist_id is None:
                return

            for existing_artist in self.artists:
                if artist_id == existing_artist.musicbrainz_artistid:
                    return existing_artist
            new_artist = MetadataDownloader.Artist(self.database, self.logger, artist_id, new_release_groups=False)
            self.artists.append(new_artist)
            return new_artist

    def download(self, option: dict):
        type_ = option['type']
        mb_id = option['id']

        if type_ == "artist":
            self.Artist(self.database, self.logger, mb_id)
        elif type_ == "release_group":
            self.ReleaseGroup(self.database, self.logger, mb_id)
        elif type_ == "release":
            self.Release(self.database, self.logger, mb_id)
        elif type_ == "track":
            self.Track(self.database, self.logger, mb_id)


if __name__ == "__main__":
    import tempfile
    import os

    temp_folder = "music-downloader"
    temp_dir = os.path.join(tempfile.gettempdir(), temp_folder)
    if not os.path.exists(temp_dir):
        os.mkdir(temp_dir)

    logging.basicConfig(level=logging.DEBUG)
    db_logger = logging.getLogger("database")
    db_logger.setLevel(logging.DEBUG)

    import database

    database_ = database.Database(os.path.join(temp_dir, "metadata.db"),
                                 os.path.join(temp_dir, "database_structure.sql"), db_logger,
                                 reset_anyways=True)

    download_logger = logging.getLogger("metadata downloader")
    download_logger.setLevel(logging.INFO)

    downloader = MetadataDownloader(database_, download_logger)

    downloader.download({'id': '5cfecbe4-f600-45e5-9038-ce820eedf3d1', 'type': 'artist'})
    # download({'id': '4b9af532-ef7e-42ab-8b26-c466327cb5e0', 'type': 'release'})
    # download({'id': 'c24ed9e7-6df9-44de-8570-975f1a5a75d1', 'type': 'track'})

from typing import List
import logging
import musicbrainzngs
import optional

try:
    from object_handeling import get_elem_from_obj, parse_music_brainz_date

except ModuleNotFoundError:
    from metadata.object_handeling import get_elem_from_obj, parse_music_brainz_date

mb_log = logging.getLogger("musicbrainzngs")
mb_log.setLevel(logging.WARNING)
musicbrainzngs.set_useragent("metadata receiver", "0.1", "https://github.com/HeIIow2/music-downloader")

OPTION_TYPES = ['artist', 'release_group', 'release', 'recording']


class Option:
    def __init__(self, type_: str, id_: str, name: str, additional_info: str = "") -> None:
        if type_ not in OPTION_TYPES:
            raise ValueError(f"type: {type_} doesn't exist. Leagal Values: {OPTION_TYPES}")
        self.type = type_
        self.name = name
        self.id = id_

        self.additional_info = additional_info

    def __repr__(self) -> str:
        type_repr = {
            'artist': 'artist\t\t',
            'release_group': 'release group\t',
            'release': 'release\t\t',
            'recording': 'recording\t'
        }
        return f"{type_repr[self.type]}: \"{self.name}\"{self.additional_info}"


class Search:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

        self.options_history = []
        self.current_option: Option

    def append_new_choices(self, new_choices: List[Option]):
        print()
        for i, choice in enumerate(new_choices):
            print(f"{str(i).zfill(2)}) {choice}")

        self.options_history.append(new_choices)

    @staticmethod
    def fetch_new_options_from_artist(artist: Option):
        """
        returning list of artist and every release group
        """
        result = musicbrainzngs.get_artist_by_id(artist.id, includes=["release-groups", "releases"])
        artist_data = get_elem_from_obj(result, ['artist'], return_if_none={})

        result = [artist]

        # sort all release groups by date and add album sort to have them in chronological order.
        release_group_list = artist_data['release-group-list']
        for i, release_group in enumerate(release_group_list):
            release_group_list[i]['first-release-date'] = parse_music_brainz_date(release_group['first-release-date'])
        release_group_list.sort(key=lambda x: x['first-release-date'])
        release_group_list = [Option("release_group", get_elem_from_obj(release_group_, ['id']),
                                     get_elem_from_obj(release_group_, ['title']),
                                     additional_info=f" ({get_elem_from_obj(release_group_, ['type'])}) from {get_elem_from_obj(release_group_, ['first-release-date'])}")
                              for release_group_ in release_group_list]

        result.extend(release_group_list)
        return result

    @staticmethod
    def fetch_new_options_from_release_group(release_group: Option):
        """
        returning list including the artists, the releases and the tracklist of the first release
        """
        results = []

        result = musicbrainzngs.get_release_group_by_id(release_group.id,
                                                        includes=["artist-credits", "releases"])
        release_group_data = get_elem_from_obj(result, ['release-group'], return_if_none={})
        artist_datas = get_elem_from_obj(release_group_data, ['artist-credit'], return_if_none={})
        release_datas = get_elem_from_obj(release_group_data, ['release-list'], return_if_none={})

        # appending all the artists to results
        for artist_data in artist_datas:
            results.append(Option('artist', get_elem_from_obj(artist_data, ['artist', 'id']),
                                  get_elem_from_obj(artist_data, ['artist', 'name'])))

        # appending initial release group
        results.append(release_group)

        # appending all releases
        first_release = None
        for i, release_data in enumerate(release_datas):
            results.append(
                Option('release', get_elem_from_obj(release_data, ['id']), get_elem_from_obj(release_data, ['title']),
                       additional_info=f" ({get_elem_from_obj(release_data, ['status'])})"))
            if i == 0:
                first_release = results[-1]

        # append tracklist of first release
        if first_release is not None:
            results.extend(Search.fetch_new_options_from_release(first_release, only_tracklist=True))

        return results

    @staticmethod
    def fetch_new_options_from_release(release: Option, only_tracklist: bool = False):
        """
        artists
        release group
        release
        tracklist
        """
        results = []
        result = musicbrainzngs.get_release_by_id(release.id,
                                                  includes=["recordings", "labels", "release-groups", "artist-credits"])
        release_data = get_elem_from_obj(result, ['release'], return_if_none={})
        label_data = get_elem_from_obj(release_data, ['label-info-list'], return_if_none={})
        recording_datas = get_elem_from_obj(release_data, ['medium-list', 0, 'track-list'], return_if_none=[])
        release_group_data = get_elem_from_obj(release_data, ['release-group'], return_if_none={})
        artist_datas = get_elem_from_obj(release_data, ['artist-credit'], return_if_none={})

        # appending all the artists to results
        for artist_data in artist_datas:
            results.append(Option('artist', get_elem_from_obj(artist_data, ['artist', 'id']),
                                  get_elem_from_obj(artist_data, ['artist', 'name'])))

        # appending the according release group
        results.append(Option("release_group", get_elem_from_obj(release_group_data, ['id']),
                              get_elem_from_obj(release_group_data, ['title']),
                              additional_info=f" ({get_elem_from_obj(release_group_data, ['type'])}) from {get_elem_from_obj(release_group_data, ['first-release-date'])}"))

        # appending the release
        results.append(release)

        # appending the tracklist, but first putting it in a list, in case of only_tracklist being True to
        # return this instead
        tracklist = []
        for i, recording_data in enumerate(recording_datas):
            recording_data = recording_data['recording']
            tracklist.append(Option('recording', get_elem_from_obj(recording_data, ['id']),
                                    get_elem_from_obj(recording_data, ['title']),
                                    f" ({get_elem_from_obj(recording_data, ['length'])}) from {get_elem_from_obj(recording_data, ['artist-credit-phrase'])}"))

        if only_tracklist:
            return tracklist
        results.extend(tracklist)
        return results

    def fetch_new_options(self):
        if self.current_option is None:
            return -1

        result = []
        if self.current_option.type == 'artist':
            result = self.fetch_new_options_from_artist(self.current_option)
        elif self.current_option.type == 'release_group':
            result = self.fetch_new_options_from_release_group(self.current_option)
        elif self.current_option.type == 'release':
            result = self.fetch_new_options_from_release(self.current_option)

        self.append_new_choices(result)

    def choose(self, index: int):
        if len(self.options_history) == 0:
            logging.error("initial query neaded before choosing")
            return -1

        latest_options = self.options_history[-1]
        if index >= len(latest_options):
            logging.error("index outside of options")
            return -1

        self.current_option = latest_options[index]
        return self.fetch_new_options()

    @staticmethod
    def search_recording_from_text(artist: str = None, release_group: str = None, recording: str = None):
        result = musicbrainzngs.search_recordings(artist=artist, release=release_group, recording=recording)
        recording_list = get_elem_from_obj(result, ['recording-list'], return_if_none=[])

        resulting_options = [
            Option("recording", get_elem_from_obj(recording_, ['id']), get_elem_from_obj(recording_, ['title']),
                   additional_info=f" of {get_elem_from_obj(recording_, ['release-list', 0, 'title'])} by {get_elem_from_obj(recording_, ['artist-credit', 0, 'name'])}")
            for recording_ in recording_list]
        return resulting_options

    @staticmethod
    def search_release_group_from_text(artist: str = None, release_group: str = None):
        result = musicbrainzngs.search_release_groups(artist=artist, releasegroup=release_group)
        release_group_list = get_elem_from_obj(result, ['release-group-list'], return_if_none=[])

        resulting_options = [Option("release_group", get_elem_from_obj(release_group_, ['id']),
                                    get_elem_from_obj(release_group_, ['title']),
                                    additional_info=f" by {get_elem_from_obj(release_group_, ['artist-credit', 0, 'name'])}")
                             for release_group_ in release_group_list]
        return resulting_options

    @staticmethod
    def search_artist_from_text(artist: str = None):
        result = musicbrainzngs.search_artists(artist=artist)
        artist_list = get_elem_from_obj(result, ['artist-list'], return_if_none=[])

        print(artist_list[0])

        resulting_options = [Option("artist", get_elem_from_obj(artist_, ['id']), get_elem_from_obj(artist_, ['name']),
                                    additional_info=f": {', '.join([i['name'] for i in get_elem_from_obj(artist_, ['tag-list'], return_if_none=[])])}")
                             for artist_ in artist_list]
        return resulting_options

    def search_from_text(self, artist: str = None, release_group: str = None, recording: str = None):
        if artist is None and release_group is None and recording is None:
            self.logger.error("either artist, release group or recording has to be set")
            return -1

        if recording is not None:
            results = self.search_recording_from_text(artist=artist, release_group=release_group, recording=recording)
        elif release_group is not None:
            results = self.search_release_group_from_text(artist=artist, release_group=release_group)
        else:
            results = self.search_artist_from_text(artist=artist)

        self.append_new_choices(results)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    logger_ = logging.getLogger("test")

    search = Search(logger=logger_)
    search.search_from_text(artist="I Prevail")
    # search.search_from_text(artist="K.I.Z")
    # search.search_from_text(artist="I Prevail", release_group="TRAUMA")
    # search.search_from_text(artist="I Prevail", release_group="TRAUMA", recording="breaking down")

    # choose an artist
    search.choose(0)
    # choose a release group
    search.choose(9)
    # choose a release
    search.choose(2)
    # choose a recording
    search.choose(4)
